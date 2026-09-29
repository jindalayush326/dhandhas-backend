"""Server-side accounting engine — the single source of truth for posting
vouchers and computing reports. Never trust a client-computed balance; every
report here is derived fresh from voucher_entries."""

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.db_transaction import db_transaction
from app.core.exceptions import NotFoundError, UnbalancedVoucherError
from app.models.transactions import Voucher, VoucherEntry


def save_voucher(
    db: Session,
    *,
    company_id: int,
    voucher_type_id: int,
    voucher_number: str,
    voucher_date: datetime,
    party_id: int | None,
    narration: str | None,
    reference_number: str | None,
    lines: list[dict],
) -> Voucher:
    """lines: [{account_id, dr_cr, amount, item_id?, godown_id?, qty?, rate?}]
    Rejects any voucher where debits and credits don't balance — the one
    invariant the whole ledger depends on. Voucher header + every entry line
    are written as a single atomic transaction: either the whole voucher
    lands, or none of it does."""
    dr = sum((Decimal(str(l["amount"])) for l in lines if l["dr_cr"] == "dr"), Decimal("0"))
    cr = sum((Decimal(str(l["amount"])) for l in lines if l["dr_cr"] == "cr"), Decimal("0"))
    if abs(dr - cr) > Decimal("0.01"):
        raise UnbalancedVoucherError(f"Unbalanced voucher: dr={dr} cr={cr}")

    with db_transaction(db):
        voucher = Voucher(
            company_id=company_id,
            voucher_type_id=voucher_type_id,
            voucher_number=voucher_number,
            voucher_date=voucher_date,
            party_id=party_id,
            narration=narration,
            reference_number=reference_number,
        )
        db.add(voucher)
        db.flush()  # assign voucher.id for the entries below
        for l in lines:
            db.add(VoucherEntry(voucher_id=voucher.id, **l))
    db.refresh(voucher)
    return voucher


def cancel_voucher(db: Session, company_id: int, voucher_id: int) -> None:
    voucher = (
        db.query(Voucher)
        .filter(Voucher.id == voucher_id, Voucher.company_id == company_id, Voucher.deleted_at.is_(None))
        .first()
    )
    if not voucher:
        raise NotFoundError(f"Voucher {voucher_id} not found")
    with db_transaction(db):
        voucher.is_cancelled = True


_TB_SQL = """
SELECT a.id AS account_id, a.name AS account_name, g.nature AS nature,
  a.opening_balance AS opening_balance, a.opening_balance_type AS ob_type,
  COALESCE(SUM(CASE WHEN ve.dr_cr = 'dr' THEN ve.amount ELSE 0 END), 0) AS dr_sum,
  COALESCE(SUM(CASE WHEN ve.dr_cr = 'cr' THEN ve.amount ELSE 0 END), 0) AS cr_sum
FROM accounts a
JOIN account_groups g ON g.id = a.group_id
LEFT JOIN voucher_entries ve ON ve.account_id = a.id AND ve.deleted_at IS NULL
LEFT JOIN vouchers v ON v.id = ve.voucher_id
  AND v.deleted_at IS NULL AND v.is_cancelled = false AND v.voucher_date <= :as_of
WHERE a.company_id = :company_id AND a.deleted_at IS NULL
GROUP BY a.id, a.name, g.nature, a.opening_balance, a.opening_balance_type
HAVING dr_sum <> 0 OR cr_sum <> 0 OR a.opening_balance <> 0
ORDER BY g.nature, a.name
"""


def trial_balance(db: Session, company_id: int, as_of: date) -> list[dict]:
    rows = db.execute(text(_TB_SQL), {"company_id": company_id, "as_of": as_of}).mappings()
    out = []
    for r in rows:
        ob_dr = r["opening_balance"] if r["ob_type"] == "dr" else 0
        ob_cr = r["opening_balance"] if r["ob_type"] == "cr" else 0
        dr = ob_dr + r["dr_sum"]
        cr = ob_cr + r["cr_sum"]
        net = dr - cr
        out.append(
            {
                "account_id": r["account_id"],
                "account_name": r["account_name"],
                "nature": r["nature"],
                "debit": net if net > 0 else 0,
                "credit": -net if net < 0 else 0,
            }
        )
    return out


_PNL_SQL = """
SELECT g.nature AS nature,
  SUM(CASE WHEN ve.dr_cr = 'cr' THEN ve.amount ELSE -ve.amount END) AS net
FROM voucher_entries ve
JOIN accounts a ON a.id = ve.account_id
JOIN account_groups g ON g.id = a.group_id
JOIN vouchers v ON v.id = ve.voucher_id
WHERE a.company_id = :company_id AND g.nature IN ('income', 'expense')
  AND v.voucher_date BETWEEN :date_from AND :date_to
  AND v.deleted_at IS NULL AND v.is_cancelled = false AND ve.deleted_at IS NULL
GROUP BY g.nature
"""


def profit_and_loss(db: Session, company_id: int, date_from: date, date_to: date) -> dict:
    rows = {
        r["nature"]: r["net"]
        for r in db.execute(
            text(_PNL_SQL), {"company_id": company_id, "date_from": date_from, "date_to": date_to}
        ).mappings()
    }
    income = rows.get("income", 0) or 0
    expense = -(rows.get("expense", 0) or 0)
    return {"income": income, "expense": expense, "net_profit": income - expense}


def balance_sheet(db: Session, company_id: int, as_of: date) -> dict:
    tb = trial_balance(db, company_id, as_of)
    return {
        "assets": [r for r in tb if r["nature"] == "asset"],
        "liabilities": [r for r in tb if r["nature"] == "liability"],
        "equity": [r for r in tb if r["nature"] == "equity"],
    }


def multi_year_pnl(db: Session, company_id: int, fy_ranges: list[tuple[date, date]]) -> list[dict]:
    """One P&L snapshot per financial year, reusing the same rules so
    multi-year comparisons stay honest."""
    return [
        {"fy_start": start, "fy_end": end, **profit_and_loss(db, company_id, start, end)}
        for start, end in fy_ranges
    ]


_LEDGER_SQL = """
SELECT v.id AS voucher_id, v.voucher_number, v.voucher_date, v.narration,
  ve.dr_cr, ve.amount
FROM voucher_entries ve
JOIN vouchers v ON v.id = ve.voucher_id
WHERE ve.account_id = :account_id AND v.company_id = :company_id
  AND v.deleted_at IS NULL AND v.is_cancelled = false AND ve.deleted_at IS NULL
  AND v.voucher_date BETWEEN :date_from AND :date_to
ORDER BY v.voucher_date, v.id
"""


def account_ledger(db: Session, company_id: int, account_id: int, date_from: date, date_to: date) -> list[dict]:
    """Statement-of-account view for one ledger — the day-to-day screen every
    accounting app needs (Tally's 'Ledger Vouchers')."""
    rows = db.execute(
        text(_LEDGER_SQL),
        {"account_id": account_id, "company_id": company_id, "date_from": date_from, "date_to": date_to},
    ).mappings()
    return [dict(r) for r in rows]
