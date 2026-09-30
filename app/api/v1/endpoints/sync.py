from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.deps import get_current_user, get_db, require_company_access
from app.core.exceptions import ForbiddenError, UnbalancedVoucherError
from app.models import core, transactions
from app.models.user import User
from app.schemas.sync import PushRequest
from app.services.realtime import manager

router = APIRouter(prefix="/sync", tags=["Sync"])

# table name -> ORM model. Add new syncable tables here only (DRY).
_TABLE_MODELS = {
    "companies": core.Company,
    "financial_years": core.FinancialYear,
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
_DECIMAL_COLUMNS = {
    "amount", "rate", "qty", "opening_balance", "opening_qty", "opening_rate",
    "gst_rate", "qty_in", "qty_out",
}

# FK column -> model it points to. Internal `*_id` values are per-database
# (autoincrement) and meaningless across devices, so pull/push translate
# them to/from the stable `uuid` instead.
_FK_MAP = {
    "company_id": core.Company,
    "financial_year_id": core.FinancialYear,
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

    row = db.query(model.id).filter(
        model.uuid == uuid_val
    ).first()

    if not row:
        raise ValueError(
            f"Sync order error: "
            f"{model.__tablename__} "
            f"{uuid_val} not found on server"
        )

    return row[0]

def _coerce_decimals(payload: dict) -> dict:
    for col in _DECIMAL_COLUMNS:
        if col in payload and payload[col] is not None:
            try:
                payload[col] = Decimal(str(payload[col]))
            except (InvalidOperation, ValueError):
                raise ValueError(f"Invalid numeric value for {col}: {payload[col]!r}")
    return payload


def _parse_dt(v):
    if not isinstance(v, str):
        return v
    dt = datetime.fromisoformat(v.replace("Z", "+00:00"))
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _coerce_datetimes(payload: dict) -> dict:
    """Clients send ISO strings; ORM DateTime columns need datetime objects."""
    for k, v in list(payload.items()):
        if v is not None and (k.endswith("_date") or k.endswith("_at") or k == "fy_start"):
            try:
                payload[k] = _parse_dt(v)
            except ValueError:
                raise ValueError(f"Invalid datetime for {k}: {v!r}")
    return payload


def _aware(dt):
    return dt if dt is None or dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _json_safe(payload: dict) -> dict:
    """For storing a row snapshot in sync_changes.payload (a JSON column) —
    Decimal/datetime aren't JSON-serializable as-is."""
    out = {}
    for k, v in payload.items():
        if isinstance(v, Decimal):
            out[k] = str(v)
        elif isinstance(v, datetime):
            out[k] = v.isoformat()
        else:
            out[k] = v
    return out


def _validate_voucher_balance(db: Session, voucher_id: int) -> None:
    """Sync bypasses accounting_engine.save_voucher, so the dr==cr invariant
    has to be re-checked here, EXACTLY (no tolerance) — otherwise a buggy or
    malicious client could push an unbalanced ledger straight into the DB."""
    rows = (
        db.query(transactions.VoucherEntry.dr_cr, transactions.VoucherEntry.amount)
        .filter(transactions.VoucherEntry.voucher_id == voucher_id, transactions.VoucherEntry.deleted_at.is_(None))
        .all()
    )
    if not rows:
        return
    dr = sum((r.amount for r in rows if r.dr_cr == "dr"), Decimal("0"))
    cr = sum((r.amount for r in rows if r.dr_cr == "cr"), Decimal("0"))
    if dr != cr:
        raise UnbalancedVoucherError(f"Unbalanced voucher {voucher_id} after sync: dr={dr} cr={cr}")


# Parents before children, always — the server does not trust client ordering.
_RANK = {
    "financial_years": 10, "account_groups": 20, "accounts": 30, "items": 40, "godowns": 50,
    "voucher_types": 60, "vouchers": 70, "voucher_entries": 80, "gst_tax_lines": 90,
    "stock_ledger_entries": 100,
}


def _ordered(changes):
    """Stable sort by table rank; account groups sorted parent-first (depth)."""
    parent = {}
    for c in changes:
        if c.table == "account_groups":
            parent[c.uuid] = c.payload.get("parent_uuid")

    def depth(u):
        d, seen = 0, set()
        while parent.get(u) and parent[u] in parent and parent[u] not in seen:
            seen.add(u)
            u = parent[u]
            d += 1
        return d

    deletes_last = lambda c: 1 if c.op == "delete" and c.table in ("vouchers", "voucher_entries", "gst_tax_lines", "stock_ledger_entries") else 0
    return sorted(
        changes,
        key=lambda c: (_RANK.get(c.table, 1000), depth(c.uuid) if c.table == "account_groups" else 0, deletes_last(c)),
    )


@router.post("/push")
async def push(
    req: PushRequest, company_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)
):
    """Apply client changes as ONE atomic transaction (all-or-nothing).

    Idempotent: `operation_id` is checked against `sync_operations` first —
    if this exact push already succeeded (e.g. the client's first attempt
    timed out waiting for a response but the server had already committed,
    and the app retried), the stored result is returned unchanged and
    NOTHING is re-applied. This is what prevents duplicate vouchers after a
    flaky network retries a push that actually already landed.

    Every applied row also gets an entry in `sync_changes` (the server's
    authoritative, sequence-ordered change log) in the SAME transaction —
    so other devices can reliably pull "everything after sequence N"
    instead of relying on updated_at, which can silently miss rows that
    share a timestamp.

    Tenant check: company_id is taken from the authenticated user's
    membership (require_company_access), never trusted bare from the
    request — a device cannot push into a company it doesn't belong to
    merely by putting a different company_id in the URL."""
    require_company_access(company_id, db, user, "sync:use")

    existing_op = (
        db.query(transactions.SyncOperation)
        .filter(transactions.SyncOperation.operation_id == req.operation_id, transactions.SyncOperation.company_id == company_id)
        .first()
    )
    if existing_op:
        return existing_op.result

    applied, skipped = 0, 0
    touched_voucher_ids: set[int] = set()

    try:
        for change in _ordered(req.changes):
            model = _TABLE_MODELS.get(change.table)
            if not model or change.table == "companies":  # company is created via POST /companies
                skipped += 1
                continue
            existing = db.query(model).filter(model.uuid == change.uuid).first()
            if existing is not None and hasattr(existing, "company_id") and existing.company_id != company_id:
                raise ForbiddenError("Entity belongs to a different company")
            raw = dict(change.payload)  # what the client sent (uuid-keyed) — this is what pull replays
            payload = dict(raw)
            payload.pop("company_uuid", None)

            for fk_col, fk_model in _FK_MAP.items():
                uuid_key = fk_col.replace("_id", "_uuid")
                if uuid_key in payload:
                    payload[fk_col] = _id_of(db, fk_model, payload.pop(uuid_key))

            payload = {k: v for k, v in payload.items() if hasattr(model, k) and k not in ("id", "uuid")}
            payload["uuid"] = change.uuid  # client uuid IS the identity; without this FK lookups by uuid fail
            if hasattr(model, "company_id"):
                payload["company_id"] = company_id  # tenant comes from the URL/membership, never the client
            payload = _coerce_datetimes(_coerce_decimals(payload))

            op_name = "delete" if change.op == "delete" else ("update" if existing else "create")

            if change.op == "delete":
                if existing:
                    existing.deleted_at = datetime.now(timezone.utc)
                applied += 1
            elif existing:
                incoming_updated = payload.get("updated_at")
                if incoming_updated and existing.updated_at and _aware(existing.updated_at) >= _aware(incoming_updated):
                    skipped += 1
                    continue
                for k, v in payload.items():
                    if k != "uuid":
                        setattr(existing, k, v)
                applied += 1
                target = existing
            else:
                target = model(**payload)
                db.add(target)
                applied += 1

            if change.op != "delete":
                db.flush()  # need target.id/company_id resolved for balance check + change-log below
                if change.table == "voucher_entries":
                    touched_voucher_ids.add(target.voucher_id)
                elif change.table == "vouchers":
                    touched_voucher_ids.add(target.id)

            db.add(transactions.SyncChange(
                company_id=company_id, entity_type=change.table, entity_id=change.uuid,
                operation=op_name, payload=_json_safe(raw), changed_at=datetime.now(timezone.utc),
                device_id=req.device_id,
            ))

        db.flush()
        for vid in touched_voucher_ids:
            _validate_voucher_balance(db, vid)

        result = {"applied": applied, "skipped": skipped}
        db.add(transactions.SyncOperation(
            operation_id=req.operation_id, company_id=company_id, device_id=req.device_id, result=result,
        ))
        db.commit()
    except HTTPException:
        db.rollback()
        raise
    except (ValueError, UnbalancedVoucherError) as e:
        db.rollback()
        raise HTTPException(status_code=422, detail=f"Sync rejected: {e}")
    except IntegrityError as e:
        db.rollback()
        raise HTTPException(status_code=409, detail=f"Sync conflict: {str(e.orig).splitlines()[0]}")
    except Exception:
        db.rollback()
        raise

    await manager.broadcast(company_id, {"type": "SYNC_CHANGED", "tables": list({c.table for c in req.changes})})
    return result


@router.get("/pull")
def pull(
    company_id: int = Query(...),
    cursor: int = Query(0, ge=0, description="Last sequence (sync_changes.id) this device has already applied"),
    limit: int = Query(500, ge=1, le=2000),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Cursor-based pull — the reliable replacement for `updated_at >
    timestamp` polling. Returns every change with sequence > cursor, in
    order, gap-free (sequence is the row's own auto-increment id, which
    Postgres guarantees is strictly increasing per insert). The client
    replays them in order and remembers `next_cursor` for its next pull —
    it will never miss a row, even if many changes landed in the same
    millisecond (a real failure mode of timestamp-based sync)."""
    require_company_access(company_id, db, user)
    rows = (
        db.query(transactions.SyncChange)
        .filter(transactions.SyncChange.company_id == company_id, transactions.SyncChange.id > cursor)
        .order_by(transactions.SyncChange.id.asc())
        .limit(limit)
        .all()
    )
    changes = [
        {
            "sequence": r.id, "entity_type": r.entity_type, "entity_id": r.entity_id,
            "operation": r.operation, "payload": r.payload, "changed_at": r.changed_at.isoformat(),
            "device_id": r.device_id,
        }
        for r in rows
    ]
    next_cursor = rows[-1].id if rows else cursor
    return {"changes": changes, "next_cursor": next_cursor, "has_more": len(rows) == limit}


@router.get("/status")
def status(
    company_id: int = Query(...),
    cursor: int = Query(0, ge=0),
    device_id: str = Query(""),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """How many changes made by OTHER devices are waiting to be pulled (badge count)."""
    require_company_access(company_id, db, user)
    n = (
        db.query(func.count(transactions.SyncChange.id))
        .filter(
            transactions.SyncChange.company_id == company_id,
            transactions.SyncChange.id > cursor,
            transactions.SyncChange.device_id != device_id,
        )
        .scalar()
    )
    return {"pending_pull": int(n or 0)}


@router.get("/pull-table", deprecated=True)
def pull_table(
    table: str = Query(...),
    since: str = Query(...),
    company_id: int = Query(...),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Legacy timestamp-based pull — kept only for backward compatibility
    with clients not yet migrated to the cursor-based GET /sync/pull above.
    New integrations should use /sync/pull, not this."""
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