from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.deps import get_current_user, get_db, require_company_access
from app.core.exceptions import UnbalancedVoucherError
from app.models import core, transactions
from app.models.user import User
from app.schemas.sync import PushRequest
from app.services.realtime import manager

router = APIRouter(prefix="/sync", tags=["Sync"])

# table name -> ORM model. Add new syncable tables here only (DRY).
_TABLE_MODELS = {
    "companies": core.Company,
    "account_groups": core.AccountGroup,
    "accounts": core.Account,
    "items": core.Item,
    "godowns": core.Godown,
    "voucher_types": core.VoucherType,
    "vouchers": transactions.Voucher,
    "voucher_entries": transactions.VoucherEntry,
    "gst_tax_lines": transactions.GstTaxLine,
    "stock_ledger_entries": transactions.StockLedgerEntry,
}

# Columns that MUST be Decimal, never float — a client (mobile app, JS,
# whatever) will send these as JSON numbers, and JSON has no decimal type.
# Coerce via str() first so e.g. 19.99 (a float) doesn't pick up binary
# floating-point error (19.990000000000002) before it ever touches money.
_DECIMAL_COLUMNS = {"amount", "rate", "qty", "opening_balance", "opening_qty", "opening_rate", "gst_rate", "qty_in", "qty_out"}

# FK column -> model it points to. Internal `*_id` values are per-database
# (autoincrement) and meaningless across devices, so pull/push translate
# them to/from the stable `uuid` instead.
_FK_MAP = {
    "company_id": core.Company,
    "group_id": core.AccountGroup,
    "parent_id": core.AccountGroup,
    "party_id": core.Account,
    "account_id": core.Account,
    "voucher_type_id": core.VoucherType,
    "voucher_id": transactions.Voucher,
    "voucher_entry_id": transactions.VoucherEntry,
    "item_id": core.Item,
    "godown_id": core.Godown,
}


def _uuid_of(db: Session, model, pk: int | None) -> str | None:
    if pk is None:
        return None
    row = db.query(model.uuid).filter(model.id == pk).first()
    return row[0] if row else None


def _id_of(db: Session, model, uuid_val: str | None) -> int | None:
    if uuid_val is None:
        return None
    row = db.query(model.id).filter(model.uuid == uuid_val).first()
    if not row:
        raise ValueError(f"Sync order error: {model.__tablename__} {uuid_val} not found on server")
    return row[0]


def _coerce_decimals(payload: dict) -> dict:
    for col in _DECIMAL_COLUMNS:
        if col in payload and payload[col] is not None:
            try:
                payload[col] = Decimal(str(payload[col]))
            except (InvalidOperation, ValueError):
                raise ValueError(f"Invalid numeric value for {col}: {payload[col]!r}")
    return payload


def _validate_voucher_balance(db: Session, voucher_id: int) -> None:
    """Sync bypasses accounting_engine.save_voucher, so the dr==cr invariant
    has to be re-checked here — otherwise a buggy/malicious client could
    push an unbalanced ledger straight into the database."""
    rows = (
        db.query(transactions.VoucherEntry.dr_cr, transactions.VoucherEntry.amount)
        .filter(transactions.VoucherEntry.voucher_id == voucher_id, transactions.VoucherEntry.deleted_at.is_(None))
        .all()
    )
    if not rows:
        return
    dr = sum((r.amount for r in rows if r.dr_cr == "dr"), Decimal("0"))
    cr = sum((r.amount for r in rows if r.dr_cr == "cr"), Decimal("0"))
    if abs(dr - cr) > Decimal("0.01"):
        raise UnbalancedVoucherError(f"Unbalanced voucher {voucher_id} after sync: dr={dr} cr={cr}")


@router.post("/push")
async def push(
    req: PushRequest, company_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)
):
    """Apply client changes as ONE atomic transaction (all-or-nothing) —
    partial application of a sync batch is worse than rejecting all of it,
    since it can leave cross-table invariants (like a voucher's dr==cr)
    broken. Conflict rule: last-write-wins on updated_at. FK values arrive
    as `*_uuid` and are resolved to this server's own `*_id` before writing.
    On success, broadcasts a lightweight ping over /sync/ws/{company_id} so
    other connected terminals pull immediately."""
    require_company_access(company_id, db, user)
    applied, skipped = 0, 0
    touched_voucher_ids: set[int] = set()

    try:
        for change in req.changes:
            model = _TABLE_MODELS.get(change.table)
            if not model:
                skipped += 1
                continue
            existing = db.query(model).filter(model.uuid == change.uuid).first()
            payload = dict(change.payload)

            for fk_col, fk_model in _FK_MAP.items():
                uuid_key = fk_col.replace("_id", "_uuid")
                if uuid_key in payload:
                    payload[fk_col] = _id_of(db, fk_model, payload.pop(uuid_key))

            payload = {k: v for k, v in payload.items() if hasattr(model, k) and k != "id"}
            payload = _coerce_decimals(payload)

            if change.op == "delete":
                if existing:
                    existing.deleted_at = datetime.now(timezone.utc)
                applied += 1
                continue

            if existing:
                incoming_updated = payload.get("updated_at")
                if incoming_updated and existing.updated_at and str(existing.updated_at) >= str(incoming_updated):
                    skipped += 1
                    continue
                for k, v in payload.items():
                    setattr(existing, k, v)
                target = existing
            else:
                target = model(**payload)
                db.add(target)
            applied += 1

            if change.table == "voucher_entries":
                db.flush()  # need target.voucher_id resolved before we can check balance
                touched_voucher_ids.add(target.voucher_id)
            elif change.table == "vouchers":
                db.flush()
                touched_voucher_ids.add(target.id)

        db.flush()
        for vid in touched_voucher_ids:
            _validate_voucher_balance(db, vid)

        db.commit()
    except Exception:
        db.rollback()
        raise

    await manager.broadcast(company_id, {"type": "SYNC_CHANGED", "tables": list({c.table for c in req.changes})})
    return {"applied": applied, "skipped": skipped}


@router.get("/pull")
def pull(
    table: str = Query(...),
    since: str = Query(...),
    company_id: int = Query(...),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Returns rows changed since [since], with every `*_id` FK replaced by
    the matching `*_uuid` so the client can resolve it to its own local id."""
    require_company_access(company_id, db, user)
    model = _TABLE_MODELS.get(table)
    if not model:
        return {"rows": []}
    since_dt = datetime.fromisoformat(since)
    q = db.query(model).filter(model.updated_at > since_dt)
    if hasattr(model, "company_id"):
        q = q.filter(model.company_id == company_id)
    rows = q.all()

    out = []
    for r in rows:
        row = {c.name: getattr(r, c.name) for c in model.__table__.columns}
        for fk_col, fk_model in _FK_MAP.items():
            if fk_col in row:
                uuid_key = fk_col.replace("_id", "_uuid")
                row[uuid_key] = _uuid_of(db, fk_model, row.pop(fk_col))
        row.pop("id", None)
        out.append(row)
    return {"rows": out, "server_time": datetime.now(timezone.utc).isoformat()}
