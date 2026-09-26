from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.deps import get_current_user, get_db, require_company_access
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


@router.post("/push")
async def push(
    req: PushRequest, company_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)
):
    """Apply client changes. Conflict rule: last-write-wins on updated_at.
    FK values arrive as `*_uuid` and are resolved to this server's own
    `*_id` before writing. On success, broadcasts a lightweight ping over
    the /sync/ws/{company_id} channel so other connected terminals pull
    immediately."""
    require_company_access(company_id, db, user)
    applied, skipped = 0, 0
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
        else:
            db.add(model(**payload))
        applied += 1
    db.commit()

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
