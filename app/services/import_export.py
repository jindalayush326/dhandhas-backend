"""Migration tooling: import masters+vouchers from Tally's XML export format,
and a generic CSV format that covers Busy (and any tool that can export to
Excel/CSV, which is effectively all of them). Also exports back out to both
formats so data can move the other way too.

Design notes:
- Every row/voucher is validated independently; a bad row is skipped and
  reported, not allowed to abort the whole import (a 5,000-row Tally export
  with 3 bad rows shouldn't force an all-or-nothing failure).
- Each voucher (whether from XML or CSV) is still run through
  accounting_engine.save_voucher, so the same dr==cr balance check applies
  to imported data as to normal API-created vouchers — imports don't get a
  back door around the core invariant.
- All amounts go through Decimal(str(...)) — never float() — from the
  moment they're read from the file.
"""
import csv
import io
import logging
import xml.etree.ElementTree as ET
from datetime import datetime
from decimal import Decimal, InvalidOperation

from sqlalchemy.orm import Session

from app.core.exceptions import UnbalancedVoucherError, ValidationError
from app.models.core import Account, AccountGroup, Item, VoucherType
from app.services import accounting_engine

logger = logging.getLogger("dhandas.import_export")

_NATURE_BY_KEYWORD = {
    "sundry debtors": "asset", "sundry creditors": "liability", "cash-in-hand": "asset",
    "bank accounts": "asset", "fixed assets": "asset", "current assets": "asset",
    "loans": "liability", "capital account": "equity", "sales accounts": "income",
    "purchase accounts": "expense", "direct expenses": "expense", "indirect expenses": "expense",
    "direct incomes": "income", "indirect incomes": "income", "duties & taxes": "liability",
}


def _guess_nature(group_name: str) -> str:
    key = (group_name or "").strip().lower()
    return _NATURE_BY_KEYWORD.get(key, "asset")


def _get_or_create_group(db: Session, company_id: int, name: str) -> AccountGroup:
    name = (name or "General").strip() or "General"
    grp = db.query(AccountGroup).filter(
        AccountGroup.company_id == company_id, AccountGroup.name == name, AccountGroup.deleted_at.is_(None)
    ).first()
    if grp:
        return grp
    grp = AccountGroup(company_id=company_id, name=name, nature=_guess_nature(name))
    db.add(grp)
    db.flush()
    return grp


def _get_or_create_account(db: Session, company_id: int, name: str, group_name: str = "General") -> Account:
    name = name.strip()
    acc = db.query(Account).filter(
        Account.company_id == company_id, Account.name == name, Account.deleted_at.is_(None)
    ).first()
    if acc:
        return acc
    group = _get_or_create_group(db, company_id, group_name)
    acc = Account(company_id=company_id, group_id=group.id, name=name)
    db.add(acc)
    db.flush()
    return acc


def _get_or_create_voucher_type(db: Session, company_id: int, name: str) -> VoucherType:
    name = (name or "Journal").strip() or "Journal"
    vt = db.query(VoucherType).filter(
        VoucherType.company_id == company_id, VoucherType.name == name, VoucherType.deleted_at.is_(None)
    ).first()
    if vt:
        return vt
    vt = VoucherType(company_id=company_id, name=name, nature=name.lower())
    db.add(vt)
    db.flush()
    return vt


def _to_decimal(value, field: str) -> Decimal:
    try:
        return Decimal(str(value).replace(",", "").strip() or "0")
    except (InvalidOperation, ValueError):
        raise ValidationError(f"Invalid number for {field}: {value!r}")


def _parse_tally_date(raw: str) -> datetime:
    raw = raw.strip()
    for fmt in ("%Y%m%d", "%d-%b-%Y", "%d/%m/%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(raw, fmt)
        except ValueError:
            continue
    raise ValidationError(f"Unrecognized date format: {raw!r}")


# ---------------------------------------------------------------------------
# Tally XML import
# ---------------------------------------------------------------------------

def import_tally_xml(db: Session, company_id: int, xml_bytes: bytes) -> dict:
    """Best-effort parser for Tally's standard XML export
    (ENVELOPE > BODY > IMPORTDATA/EXPORTDATA > REQUESTDATA > TALLYMESSAGE).
    Covers LEDGER, STOCKITEM, and VOUCHER nodes — the common case for a
    company-data export. Tally's schema varies slightly across versions;
    unrecognized nodes are skipped, not fatal.
    """
    try:
        root = ET.fromstring(xml_bytes)
    except ET.ParseError as exc:
        raise ValidationError(f"Invalid XML: {exc}")

    ledgers_created = items_created = vouchers_created = 0
    errors: list[str] = []

    messages = root.findall(".//TALLYMESSAGE")

    # Pass 1: ledgers (accounts) — vouchers reference these by name
    for msg in messages:
        ledger = msg.find("LEDGER")
        if ledger is None:
            continue
        try:
            name = ledger.get("NAME") or (ledger.findtext("NAME") or "")
            parent = ledger.findtext("PARENT") or "General"
            acc = _get_or_create_account(db, company_id, name, parent)
            ob = ledger.findtext("OPENINGBALANCE")
            if ob:
                amt = _to_decimal(ob, "OPENINGBALANCE")
                acc.opening_balance_type = "dr" if amt >= 0 else "cr"
                acc.opening_balance = abs(amt)
            gstin = ledger.findtext("PARTYGSTIN") or ledger.findtext("GSTIN")
            if gstin:
                acc.gstin = gstin.strip()
            ledgers_created += 1
        except Exception as exc:
            errors.append(f"LEDGER {ledger.get('NAME', '?')}: {exc}")

    # Pass 2: stock items
    for msg in messages:
        stock_item = msg.find("STOCKITEM")
        if stock_item is None:
            continue
        try:
            name = stock_item.get("NAME") or (stock_item.findtext("NAME") or "")
            unit = stock_item.findtext("BASEUNITS") or "NOS"
            existing = db.query(Item).filter(
                Item.company_id == company_id, Item.name == name.strip(), Item.deleted_at.is_(None)
            ).first()
            if not existing:
                db.add(Item(company_id=company_id, name=name.strip(), unit=unit))
                db.flush()
            items_created += 1
        except Exception as exc:
            errors.append(f"STOCKITEM {stock_item.get('NAME', '?')}: {exc}")

    db.flush()

    # Pass 3: vouchers (each becomes one accounting_engine.save_voucher call)
    for msg in messages:
        voucher = msg.find("VOUCHER")
        if voucher is None:
            continue
        try:
            vch_type = voucher.get("VCHTYPE") or voucher.findtext("VOUCHERTYPENAME") or "Journal"
            vch_number = voucher.findtext("VOUCHERNUMBER") or ""
            vch_date_raw = voucher.findtext("DATE") or ""
            narration = voucher.findtext("NARRATION") or ""
            party_name = voucher.findtext("PARTYLEDGERNAME")

            lines = []
            for entry in voucher.findall("ALLLEDGERENTRIES.LIST") + voucher.findall("LEDGERENTRIES.LIST"):
                ledger_name = entry.findtext("LEDGERNAME")
                amount_raw = entry.findtext("AMOUNT") or "0"
                is_positive = (entry.findtext("ISDEEMEDPOSITIVE") or "No").strip().lower() == "yes"
                amount = abs(_to_decimal(amount_raw, "AMOUNT"))
                if amount == 0:
                    continue
                account = _get_or_create_account(db, company_id, ledger_name or "Suspense")
                lines.append({
                    "account_id": account.id,
                    "dr_cr": "dr" if is_positive else "cr",
                    "amount": amount,
                })

            if not lines:
                errors.append(f"VOUCHER {vch_number}: no ledger entries found, skipped")
                continue

            vt = _get_or_create_voucher_type(db, company_id, vch_type)
            party = _get_or_create_account(db, company_id, party_name) if party_name else None
            db.flush()

            accounting_engine.save_voucher(
                db, company_id=company_id, voucher_type_id=vt.id,
                voucher_number=vch_number or f"IMPORT-{vouchers_created + 1}",
                voucher_date=_parse_tally_date(vch_date_raw) if vch_date_raw else datetime.utcnow(),
                party_id=party.id if party else None, narration=narration,
                reference_number=None, lines=lines,
            )
            vouchers_created += 1
        except UnbalancedVoucherError as exc:
            errors.append(f"VOUCHER {voucher.findtext('VOUCHERNUMBER', '?')}: {exc}")
        except Exception as exc:
            errors.append(f"VOUCHER {voucher.findtext('VOUCHERNUMBER', '?')}: {exc}")

    db.commit()
    return {
        "ledgers_imported": ledgers_created, "items_imported": items_created,
        "vouchers_imported": vouchers_created, "errors": errors,
    }


def export_tally_xml(db: Session, company_id: int) -> bytes:
    """Exports accounts + vouchers in Tally's XML import format, so the data
    can be pulled into Tally (or re-imported here, or into another tool that
    understands the same schema)."""
    from app.models.transactions import Voucher, VoucherEntry

    envelope = ET.Element("ENVELOPE")
    body = ET.SubElement(envelope, "BODY")
    import_data = ET.SubElement(body, "IMPORTDATA")
    request_data = ET.SubElement(import_data, "REQUESTDATA")

    accounts = db.query(Account).filter(Account.company_id == company_id, Account.deleted_at.is_(None)).all()
    for acc in accounts:
        msg = ET.SubElement(request_data, "TALLYMESSAGE")
        ledger = ET.SubElement(msg, "LEDGER", NAME=acc.name, ACTION="Create")
        ET.SubElement(ledger, "NAME").text = acc.name
        group = db.query(AccountGroup).filter(AccountGroup.id == acc.group_id).first()
        ET.SubElement(ledger, "PARENT").text = group.name if group else "General"
        ob = acc.opening_balance if acc.opening_balance_type == "dr" else -acc.opening_balance
        ET.SubElement(ledger, "OPENINGBALANCE").text = str(ob)
        if acc.gstin:
            ET.SubElement(ledger, "PARTYGSTIN").text = acc.gstin

    vouchers = (
        db.query(Voucher)
        .filter(Voucher.company_id == company_id, Voucher.deleted_at.is_(None), Voucher.is_cancelled.is_(False))
        .all()
    )
    for v in vouchers:
        vt = db.query(VoucherType).filter(VoucherType.id == v.voucher_type_id).first()
        msg = ET.SubElement(request_data, "TALLYMESSAGE")
        voucher_el = ET.SubElement(msg, "VOUCHER", VCHTYPE=vt.name if vt else "Journal", ACTION="Create")
        ET.SubElement(voucher_el, "DATE").text = v.voucher_date.strftime("%Y%m%d")
        ET.SubElement(voucher_el, "VOUCHERNUMBER").text = v.voucher_number
        if v.narration:
            ET.SubElement(voucher_el, "NARRATION").text = v.narration
        entries = db.query(VoucherEntry).filter(
            VoucherEntry.voucher_id == v.id, VoucherEntry.deleted_at.is_(None)
        ).all()
        for e in entries:
            account = db.query(Account).filter(Account.id == e.account_id).first()
            entry_el = ET.SubElement(voucher_el, "ALLLEDGERENTRIES.LIST")
            ET.SubElement(entry_el, "LEDGERNAME").text = account.name if account else ""
            ET.SubElement(entry_el, "ISDEEMEDPOSITIVE").text = "Yes" if e.dr_cr == "dr" else "No"
            amt = e.amount if e.dr_cr == "dr" else -e.amount
            ET.SubElement(entry_el, "AMOUNT").text = str(amt)

    return b'<?xml version="1.0" encoding="UTF-8"?>\n' + ET.tostring(envelope, encoding="utf-8")


# ---------------------------------------------------------------------------
# Generic CSV import/export — for Busy, Excel, or anything else that can
# export a flat table. Busy has no public documented XML/API schema, so CSV
# (via Busy's own "Export to Excel" then Save As CSV) is the practical path.
# ---------------------------------------------------------------------------

# Expected headers, documented here so the person exporting from Busy/Excel
# knows exactly what to name their columns.
LEDGER_CSV_HEADERS = ["name", "group", "opening_balance", "opening_balance_type", "gstin"]
ITEM_CSV_HEADERS = ["name", "hsn_code", "unit", "gst_rate", "opening_qty", "opening_rate"]
# Voucher CSV: one row per ledger entry, grouped by voucher_number — a
# voucher with 3 legs (1 debit, 2 credits) is 3 rows sharing voucher_number.
VOUCHER_CSV_HEADERS = ["voucher_number", "voucher_type", "date", "ledger_name", "dr_cr", "amount", "narration"]


def import_csv_ledgers(db: Session, company_id: int, csv_text: str) -> dict:
    reader = csv.DictReader(io.StringIO(csv_text))
    created, errors = 0, []
    for i, row in enumerate(reader, start=2):  # row 1 is the header
        try:
            name = (row.get("name") or "").strip()
            if not name:
                raise ValidationError("name is required")
            acc = _get_or_create_account(db, company_id, name, row.get("group") or "General")
            ob = row.get("opening_balance")
            if ob:
                acc.opening_balance = abs(_to_decimal(ob, "opening_balance"))
                acc.opening_balance_type = (row.get("opening_balance_type") or "dr").strip().lower()
            if row.get("gstin"):
                acc.gstin = row["gstin"].strip()
            created += 1
        except Exception as exc:
            errors.append(f"row {i}: {exc}")
    db.commit()
    return {"ledgers_imported": created, "errors": errors}


def import_csv_items(db: Session, company_id: int, csv_text: str) -> dict:
    reader = csv.DictReader(io.StringIO(csv_text))
    created, errors = 0, []
    for i, row in enumerate(reader, start=2):
        try:
            name = (row.get("name") or "").strip()
            if not name:
                raise ValidationError("name is required")
            existing = db.query(Item).filter(
                Item.company_id == company_id, Item.name == name, Item.deleted_at.is_(None)
            ).first()
            item = existing or Item(company_id=company_id, name=name)
            item.hsn_code = row.get("hsn_code") or item.hsn_code
            item.unit = row.get("unit") or getattr(item, "unit", "NOS") or "NOS"
            if row.get("gst_rate"):
                item.gst_rate = _to_decimal(row["gst_rate"], "gst_rate")
            if row.get("opening_qty"):
                item.opening_qty = _to_decimal(row["opening_qty"], "opening_qty")
            if row.get("opening_rate"):
                item.opening_rate = _to_decimal(row["opening_rate"], "opening_rate")
            if not existing:
                db.add(item)
            created += 1
        except Exception as exc:
            errors.append(f"row {i}: {exc}")
    db.commit()
    return {"items_imported": created, "errors": errors}


def import_csv_vouchers(db: Session, company_id: int, csv_text: str) -> dict:
    reader = csv.DictReader(io.StringIO(csv_text))
    rows_by_voucher: dict[str, list[dict]] = {}
    for row in reader:
        rows_by_voucher.setdefault(row.get("voucher_number", "").strip(), []).append(row)

    created, errors = 0, []
    for vch_number, rows in rows_by_voucher.items():
        try:
            if not vch_number:
                raise ValidationError("voucher_number is required")
            first = rows[0]
            vt = _get_or_create_voucher_type(db, company_id, first.get("voucher_type") or "Journal")
            lines = []
            for row in rows:
                account = _get_or_create_account(db, company_id, row["ledger_name"])
                dr_cr = (row.get("dr_cr") or "").strip().lower()
                if dr_cr not in ("dr", "cr"):
                    raise ValidationError(f"dr_cr must be 'dr' or 'cr', got {dr_cr!r}")
                lines.append({
                    "account_id": account.id, "dr_cr": dr_cr,
                    "amount": _to_decimal(row["amount"], "amount"),
                })
            db.flush()
            accounting_engine.save_voucher(
                db, company_id=company_id, voucher_type_id=vt.id, voucher_number=vch_number,
                voucher_date=_parse_tally_date(first.get("date", "")) if first.get("date") else datetime.utcnow(),
                party_id=None, narration=first.get("narration"), reference_number=None, lines=lines,
            )
            created += 1
        except Exception as exc:
            errors.append(f"voucher {vch_number}: {exc}")
    return {"vouchers_imported": created, "errors": errors}


def export_csv_ledgers(db: Session, company_id: int) -> str:
    accounts = db.query(Account).filter(Account.company_id == company_id, Account.deleted_at.is_(None)).all()
    out = io.StringIO()
    writer = csv.DictWriter(out, fieldnames=LEDGER_CSV_HEADERS)
    writer.writeheader()
    for acc in accounts:
        group = db.query(AccountGroup).filter(AccountGroup.id == acc.group_id).first()
        writer.writerow({
            "name": acc.name, "group": group.name if group else "",
            "opening_balance": str(acc.opening_balance), "opening_balance_type": acc.opening_balance_type,
            "gstin": acc.gstin or "",
        })
    return out.getvalue()


def export_csv_items(db: Session, company_id: int) -> str:
    items = db.query(Item).filter(Item.company_id == company_id, Item.deleted_at.is_(None)).all()
    out = io.StringIO()
    writer = csv.DictWriter(out, fieldnames=ITEM_CSV_HEADERS)
    writer.writeheader()
    for it in items:
        writer.writerow({
            "name": it.name, "hsn_code": it.hsn_code or "", "unit": it.unit,
            "gst_rate": str(it.gst_rate), "opening_qty": str(it.opening_qty), "opening_rate": str(it.opening_rate),
        })
    return out.getvalue()


def export_csv_vouchers(db: Session, company_id: int) -> str:
    from app.models.transactions import Voucher, VoucherEntry

    vouchers = db.query(Voucher).filter(Voucher.company_id == company_id, Voucher.deleted_at.is_(None)).all()
    out = io.StringIO()
    writer = csv.DictWriter(out, fieldnames=VOUCHER_CSV_HEADERS)
    writer.writeheader()
    for v in vouchers:
        vt = db.query(VoucherType).filter(VoucherType.id == v.voucher_type_id).first()
        entries = db.query(VoucherEntry).filter(
            VoucherEntry.voucher_id == v.id, VoucherEntry.deleted_at.is_(None)
        ).all()
        for e in entries:
            account = db.query(Account).filter(Account.id == e.account_id).first()
            writer.writerow({
                "voucher_number": v.voucher_number, "voucher_type": vt.name if vt else "",
                "date": v.voucher_date.strftime("%Y-%m-%d"), "ledger_name": account.name if account else "",
                "dr_cr": e.dr_cr, "amount": str(e.amount), "narration": v.narration or "",
            })
    return out.getvalue()
