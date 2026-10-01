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


# ============================================================
# SYNCABLE TABLES
# ============================================================

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

    # Udhaar / bill-wise accounting
    "bills": transactions.Bill,
    "bill_allocations": transactions.BillAllocation,
}


# ============================================================
# DECIMAL COLUMNS
# ============================================================

_DECIMAL_COLUMNS = {
    "amount",
    "rate",
    "qty",
    "opening_balance",
    "opening_qty",
    "opening_rate",
    "gst_rate",
    "qty_in",
    "qty_out",

    # Udhaar
    "original",
    "outstanding",
}


# ============================================================
# FOREIGN KEY MAP
# ============================================================

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

    # Udhaar
    "bill_id": transactions.Bill,
    "source_voucher_id": transactions.Voucher,
}


# ============================================================
# BASIC UUID / ID HELPERS
# ============================================================

def _uuid_of(
    db: Session,
    model,
    pk: int | None,
) -> str | None:
    if pk is None:
        return None

    row = (
        db.query(model.uuid)
        .filter(model.id == pk)
        .first()
    )

    return row[0] if row else None


def _id_of(
    db: Session,
    model,
    uuid_val: str | None,
) -> int | None:
    if uuid_val is None:
        return None

    row = (
        db.query(model.id)
        .filter(model.uuid == uuid_val)
        .first()
    )

    if not row:
        raise ValueError(
            f"Sync order error: "
            f"{model.__tablename__} "
            f"{uuid_val} not found on server"
        )

    return row[0]


# ============================================================
# DATA CONVERSION
# ============================================================

def _coerce_decimals(payload: dict) -> dict:
    for col in _DECIMAL_COLUMNS:
        if col in payload and payload[col] is not None:
            try:
                payload[col] = Decimal(str(payload[col]))
            except (InvalidOperation, ValueError):
                raise ValueError(
                    f"Invalid numeric value for {col}: "
                    f"{payload[col]!r}"
                )

    return payload


def _parse_dt(v):
    if not isinstance(v, str):
        return v

    try:
        dt = datetime.fromisoformat(
            v.replace("Z", "+00:00")
        )
    except ValueError:
        raise ValueError(
            f"Invalid datetime value: {v!r}"
        )

    return (
        dt
        if dt.tzinfo
        else dt.replace(tzinfo=timezone.utc)
    )


def _coerce_datetimes(payload: dict) -> dict:
    for k, v in list(payload.items()):
        if (
            v is not None
            and (
                k.endswith("_date")
                or k.endswith("_at")
                or k == "fy_start"
            )
        ):
            payload[k] = _parse_dt(v)

    return payload


def _aware(dt):
    if dt is None:
        return None

    return (
        dt
        if dt.tzinfo
        else dt.replace(tzinfo=timezone.utc)
    )


def _json_safe(payload: dict) -> dict:
    """
    Make payload safe for JSON storage inside sync_changes.
    """
    out = {}

    for k, v in payload.items():
        if isinstance(v, Decimal):
            out[k] = str(v)
        elif isinstance(v, datetime):
            out[k] = v.isoformat()
        else:
            out[k] = v

    return out


# ============================================================
# VOUCHER VALIDATION
# ============================================================

def _validate_voucher_balance(
    db: Session,
    voucher_id: int,
) -> None:
    """
    Sync bypasses the normal accounting engine.

    Therefore every synced voucher must still satisfy:

        total debit == total credit
    """

    rows = (
        db.query(
            transactions.VoucherEntry.dr_cr,
            transactions.VoucherEntry.amount,
        )
        .filter(
            transactions.VoucherEntry.voucher_id == voucher_id,
            transactions.VoucherEntry.deleted_at.is_(None),
        )
        .all()
    )

    if not rows:
        return

    dr = sum(
        (
            r.amount
            for r in rows
            if r.dr_cr == "dr"
        ),
        Decimal("0"),
    )

    cr = sum(
        (
            r.amount
            for r in rows
            if r.dr_cr == "cr"
        ),
        Decimal("0"),
    )

    if dr != cr:
        raise UnbalancedVoucherError(
            f"Unbalanced voucher {voucher_id}: "
            f"dr={dr} cr={cr}"
        )


# ============================================================
# SYNC ORDER
# ============================================================

_RANK = {
    "financial_years": 10,
    "account_groups": 20,
    "accounts": 30,
    "items": 40,
    "godowns": 50,
    "voucher_types": 60,

    "vouchers": 70,
    "voucher_entries": 80,
    "gst_tax_lines": 90,
    "stock_ledger_entries": 100,

    # Udhaar
    "bills": 110,
    "bill_allocations": 120,
}


def _ordered(changes):
    """
    Server controls sync ordering.

    Parents are always processed before children.
    """

    parent = {}

    for c in changes:
        if c.table == "account_groups":
            parent[c.uuid] = c.payload.get(
                "parent_uuid"
            )

    def depth(u):
        d = 0
        seen = set()

        while (
            parent.get(u)
            and parent[u] in parent
            and parent[u] not in seen
        ):
            seen.add(u)
            u = parent[u]
            d += 1

        return d

    def deletes_last(c):
        if (
            c.op == "delete"
            and c.table in {
                "vouchers",
                "voucher_entries",
                "gst_tax_lines",
                "stock_ledger_entries",
                "bills",
                "bill_allocations",
            }
        ):
            return 1

        return 0

    return sorted(
        changes,
        key=lambda c: (
            _RANK.get(c.table, 1000),
            (
                depth(c.uuid)
                if c.table == "account_groups"
                else 0
            ),
            deletes_last(c),
        ),
    )


# ============================================================
# BILL VALIDATION
# ============================================================

def _validate_bill(
    db: Session,
    bill: transactions.Bill,
) -> None:

    if bill.side not in ("dr", "cr"):
        raise ValueError(
            "Bill side must be 'dr' or 'cr'"
        )

    if bill.status not in (
        "open",
        "part",
        "paid",
    ):
        raise ValueError(
            "Invalid bill status"
        )

    if bill.original < Decimal("0"):
        raise ValueError(
            "Bill original cannot be negative"
        )

    if bill.outstanding < Decimal("0"):
        raise ValueError(
            "Bill outstanding cannot be negative"
        )

    if bill.outstanding > bill.original:
        raise ValueError(
            "Bill outstanding cannot exceed original"
        )

    party = (
        db.query(core.Account)
        .filter(
            core.Account.id == bill.party_id,
            core.Account.deleted_at.is_(None),
        )
        .first()
    )

    if not party:
        raise ValueError(
            f"Bill {bill.uuid} party does not exist"
        )

    if party.company_id != bill.company_id:
        raise ForbiddenError(
            "Bill party belongs to another company"
        )


# ============================================================
# BILL ALLOCATION VALIDATION
# ============================================================

def _validate_bill_allocation(
    db: Session,
    allocation: transactions.BillAllocation,
) -> None:

    if allocation.amount <= Decimal("0"):
        raise ValueError(
            "Allocation amount must be greater than zero"
        )

    bill = (
        db.query(transactions.Bill)
        .filter(
            transactions.Bill.id == allocation.bill_id,
            transactions.Bill.deleted_at.is_(None),
        )
        .first()
    )

    if not bill:
        raise ValueError(
            f"Bill for allocation "
            f"{allocation.uuid} does not exist"
        )

    if bill.company_id != allocation.company_id:
        raise ForbiddenError(
            "Bill belongs to another company"
        )

    if bill.party_id != allocation.party_id:
        raise ValueError(
            "Allocation party does not match bill party"
        )

    if allocation.source_voucher_id is not None:

        voucher = (
            db.query(transactions.Voucher)
            .filter(
                transactions.Voucher.id
                == allocation.source_voucher_id,
                transactions.Voucher.deleted_at.is_(None),
            )
            .first()
        )

        if not voucher:
            raise ValueError(
                "Source voucher does not exist"
            )

        if voucher.company_id != allocation.company_id:
            raise ForbiddenError(
                "Source voucher belongs to another company"
            )


# ============================================================
# ALLOCATION TOTAL VALIDATION
# ============================================================

def _allocation_total(
    db: Session,
    bill_id: int,
) -> Decimal:

    total = (
        db.query(
            func.coalesce(
                func.sum(
                    transactions.BillAllocation.amount
                ),
                0,
            )
        )
        .filter(
            transactions.BillAllocation.bill_id
            == bill_id,
            transactions.BillAllocation.deleted_at.is_(None),
        )
        .scalar()
    )

    return Decimal(str(total or 0))


def _validate_bill_allocation_total(
    db: Session,
    bill: transactions.Bill,
) -> Decimal:

    allocated = _allocation_total(
        db,
        bill.id,
    )

    if allocated < Decimal("0"):
        raise ValueError(
            "Total bill allocation cannot be negative"
        )

    if allocated > bill.original:
        raise ValueError(
            f"Bill {bill.uuid} is over-allocated: "
            f"allocated={allocated}, "
            f"original={bill.original}"
        )

    return allocated


# ============================================================
# RECALCULATE BILL
# ============================================================

def _recalculate_bill(
    db: Session,
    bill: transactions.Bill,
) -> None:
    """
    Server-authoritative bill balance.

    outstanding = original - active allocations

    status:
        open = nothing allocated
        part = partially allocated
        paid = fully allocated
    """

    allocated = (
        _validate_bill_allocation_total(
            db,
            bill,
        )
    )

    outstanding = (
        bill.original - allocated
    )

    if outstanding < Decimal("0"):
        raise ValueError(
            f"Bill {bill.uuid} has negative outstanding"
        )

    if outstanding == Decimal("0"):
        status = "paid"
    elif allocated > Decimal("0"):
        status = "part"
    else:
        status = "open"

    bill.outstanding = outstanding
    bill.status = status


# ============================================================
# PUSH
# ============================================================

@router.post("/push")
async def push(
    req: PushRequest,
    company_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """
    Apply client changes as ONE atomic transaction.

    Important properties:

    1. Tenant protected.
    2. Idempotent operation_id.
    3. Server-controlled ordering.
    4. UUID based FK resolution.
    5. Opening-balance allocation support.
    6. Voucher balance validation.
    7. Bill validation.
    8. Bill allocation validation.
    9. Server-side outstanding/status calculation.
    10. Authoritative sync_changes log.
    """

    require_company_access(
        company_id,
        db,
        user,
        "sync:use",
    )

    # --------------------------------------------------------
    # IDEMPOTENCY
    # --------------------------------------------------------

    existing_op = (
        db.query(transactions.SyncOperation)
        .filter(
            transactions.SyncOperation.operation_id
            == req.operation_id,
            transactions.SyncOperation.company_id
            == company_id,
        )
        .first()
    )

    if existing_op:
        return existing_op.result

    applied = 0
    skipped = 0

    touched_voucher_ids: set[int] = set()
    touched_bill_ids: set[int] = set()

    try:

        # ----------------------------------------------------
        # APPLY CHANGES
        # ----------------------------------------------------

        for change in _ordered(req.changes):

            model = _TABLE_MODELS.get(
                change.table
            )

            if (
                not model
                or change.table == "companies"
            ):
                skipped += 1
                continue

            existing = (
                db.query(model)
                .filter(
                    model.uuid == change.uuid
                )
                .first()
            )

            # ------------------------------------------------
            # TENANT CHECK
            # ------------------------------------------------

            if (
                existing is not None
                and hasattr(existing, "company_id")
                and existing.company_id != company_id
            ):
                raise ForbiddenError(
                    "Entity belongs to a different company"
                )

            # ------------------------------------------------
            # PAYLOAD
            # ------------------------------------------------

            raw = dict(change.payload)
            payload = dict(raw)

            payload.pop(
                "company_uuid",
                None,
            )

            # ------------------------------------------------
            # SPECIAL OPENING-BALANCE ALLOCATION
            # ------------------------------------------------
            #
            # Example:
            #
            # source_voucher_uuid =
            #     "ob_<account_uuid>"
            #
            # This is NOT a real Voucher.
            # Therefore it must NOT go through _id_of()
            # against transactions.Voucher.
            #

            if change.table == "bill_allocations":

                source_uuid = payload.get(
                    "source_voucher_uuid"
                )

                if (
                    source_uuid
                    and source_uuid.startswith("ob_")
                ):
                    payload.pop(
                        "source_voucher_uuid",
                        None,
                    )

                    payload[
                        "source_voucher_id"
                    ] = None

            # ------------------------------------------------
            # GENERIC FK UUID -> INTERNAL ID
            # ------------------------------------------------

            for fk_col, fk_model in _FK_MAP.items():

                # Opening balance already handled above.
                if (
                    change.table
                    == "bill_allocations"
                    and fk_col
                    == "source_voucher_id"
                    and payload.get(
                        "source_voucher_id"
                    ) is None
                ):
                    continue

                uuid_key = (
                    fk_col.replace(
                        "_id",
                        "_uuid",
                    )
                )

                if uuid_key in payload:

                    payload[fk_col] = _id_of(
                        db,
                        fk_model,
                        payload.pop(uuid_key),
                    )

            # ------------------------------------------------
            # KEEP ONLY REAL ORM COLUMNS
            # ------------------------------------------------

            payload = {
                k: v
                for k, v in payload.items()
                if hasattr(model, k)
                and k not in (
                    "id",
                    "uuid",
                )
            }

            # Client UUID is authoritative identity.
            payload["uuid"] = change.uuid

            # Server determines company.
            if hasattr(model, "company_id"):
                payload["company_id"] = (
                    company_id
                )

            # ------------------------------------------------
            # CONVERT NUMBERS / DATETIMES
            # ------------------------------------------------

            payload = _coerce_decimals(
                payload
            )

            payload = _coerce_datetimes(
                payload
            )

            # ------------------------------------------------
            # OPERATION
            # ------------------------------------------------

            op_name = (
                "delete"
                if change.op == "delete"
                else (
                    "update"
                    if existing
                    else "create"
                )
            )

            # ------------------------------------------------
            # DELETE
            # ------------------------------------------------

            if change.op == "delete":

                if existing:

                    # If deleting an allocation,
                    # remember its bill so the bill can
                    # be recalculated after deletion.
                    if (
                        change.table
                        == "bill_allocations"
                    ):
                        if (
                            existing.bill_id
                            is not None
                        ):
                            touched_bill_ids.add(
                                existing.bill_id
                            )

                    existing.deleted_at = (
                        datetime.now(timezone.utc)
                    )

                applied += 1

            # ------------------------------------------------
            # UPDATE
            # ------------------------------------------------

            elif existing:

                incoming_updated = payload.get(
                    "updated_at"
                )

                if (
                    incoming_updated
                    and existing.updated_at
                    and _aware(
                        existing.updated_at
                    )
                    >= _aware(
                        incoming_updated
                    )
                ):
                    skipped += 1
                    continue

                # Allocation update:
                # remember old bill before changing it.
                if (
                    change.table
                    == "bill_allocations"
                ):
                    if (
                        existing.bill_id
                        is not None
                    ):
                        touched_bill_ids.add(
                            existing.bill_id
                        )

                for k, v in payload.items():

                    if k != "uuid":
                        setattr(
                            existing,
                            k,
                            v,
                        )

                applied += 1
                target = existing

            # ------------------------------------------------
            # CREATE
            # ------------------------------------------------

            else:

                target = model(
                    **payload
                )

                db.add(target)

                applied += 1

            # ------------------------------------------------
            # POST-CHANGE TRACKING
            # ------------------------------------------------

            if change.op != "delete":

                db.flush()

                if change.table == "voucher_entries":

                    if target.voucher_id is not None:
                        touched_voucher_ids.add(
                            target.voucher_id
                        )

                elif change.table == "vouchers":

                    touched_voucher_ids.add(
                        target.id
                    )

                elif change.table == "bills":

                    touched_bill_ids.add(
                        target.id
                    )

                elif (
                    change.table
                    == "bill_allocations"
                ):

                    if target.bill_id is not None:
                        touched_bill_ids.add(
                            target.bill_id
                        )

            # ------------------------------------------------
            # SERVER CHANGE LOG
            # ------------------------------------------------

            db.add(
                transactions.SyncChange(
                    company_id=company_id,
                    entity_type=change.table,
                    entity_id=change.uuid,
                    operation=op_name,
                    payload=_json_safe(raw),
                    changed_at=datetime.now(
                        timezone.utc
                    ),
                    device_id=req.device_id,
                )
            )

        # ----------------------------------------------------
        # FLUSH ALL CHANGES
        # ----------------------------------------------------

        db.flush()

        # ----------------------------------------------------
        # RECALCULATE / VALIDATE BILLS
        # ----------------------------------------------------

        for bill_id in touched_bill_ids:

            bill = (
                db.query(
                    transactions.Bill
                )
                .filter(
                    transactions.Bill.id
                    == bill_id
                )
                .first()
            )

            # Bill itself may have been deleted.
            if not bill:
                continue

            if bill.deleted_at is not None:
                continue

            _validate_bill(
                db,
                bill,
            )

            _recalculate_bill(
                db,
                bill,
            )

            # Make sure SQLAlchemy sees the new values.
            db.flush()

        # ----------------------------------------------------
        # VALIDATE ACTIVE ALLOCATIONS
        # ----------------------------------------------------

        for bill_id in touched_bill_ids:

            allocations = (
                db.query(
                    transactions.BillAllocation
                )
                .filter(
                    transactions.BillAllocation.bill_id
                    == bill_id,
                    transactions.BillAllocation.deleted_at
                    .is_(None),
                )
                .all()
            )

            for allocation in allocations:

                _validate_bill_allocation(
                    db,
                    allocation,
                )

        # ----------------------------------------------------
        # VALIDATE VOUCHERS
        # ----------------------------------------------------

        for voucher_id in touched_voucher_ids:

            voucher = (
                db.query(
                    transactions.Voucher
                )
                .filter(
                    transactions.Voucher.id
                    == voucher_id
                )
                .first()
            )

            if not voucher:
                continue

            if voucher.deleted_at is not None:
                continue

            _validate_voucher_balance(
                db,
                voucher_id,
            )

        # ----------------------------------------------------
        # FINAL FLUSH
        # ----------------------------------------------------

        db.flush()

        # ----------------------------------------------------
        # IDEMPOTENCY RESULT
        # ----------------------------------------------------

        result = {
            "applied": applied,
            "skipped": skipped,
        }

        db.add(
            transactions.SyncOperation(
                operation_id=req.operation_id,
                company_id=company_id,
                device_id=req.device_id,
                result=result,
            )
        )

        # ----------------------------------------------------
        # COMMIT EVERYTHING AT ONCE
        # ----------------------------------------------------

        db.commit()

    except HTTPException:

        db.rollback()
        raise

    except (
        ValueError,
        UnbalancedVoucherError,
    ) as e:

        db.rollback()

        raise HTTPException(
            status_code=422,
            detail=f"Sync rejected: {e}",
        )

    except IntegrityError as e:

        db.rollback()

        raise HTTPException(
            status_code=409,
            detail=(
                "Sync conflict: "
                f"{str(e.orig).splitlines()[0]}"
            ),
        )

    except Exception:

        db.rollback()
        raise

    # --------------------------------------------------------
    # REALTIME NOTIFICATION
    # --------------------------------------------------------

    await manager.broadcast(
        company_id,
        {
            "type": "SYNC_CHANGED",
            "tables": list(
                {
                    c.table
                    for c in req.changes
                }
            ),
        },
    )

    return result


# ============================================================
# CURSOR-BASED PULL
# ============================================================

@router.get("/pull")
def pull(
    company_id: int = Query(...),
    cursor: int = Query(
        0,
        ge=0,
        description=(
            "Last sync_changes.id already "
            "applied by this device"
        ),
    ),
    limit: int = Query(
        500,
        ge=1,
        le=2000,
    ),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """
    Cursor-based pull.

    The cursor is the server-side sync_changes.id,
    NOT updated_at.

    This prevents missed changes when several rows have
    identical timestamps.
    """

    require_company_access(
        company_id,
        db,
        user,
    )

    rows = (
        db.query(
            transactions.SyncChange
        )
        .filter(
            transactions.SyncChange.company_id
            == company_id,
            transactions.SyncChange.id
            > cursor,
        )
        .order_by(
            transactions.SyncChange.id.asc()
        )
        .limit(limit)
        .all()
    )

    changes = [
        {
            "sequence": r.id,
            "entity_type": r.entity_type,
            "entity_id": r.entity_id,
            "operation": r.operation,
            "payload": r.payload,
            "changed_at": (
                r.changed_at.isoformat()
            ),
            "device_id": r.device_id,
        }
        for r in rows
    ]

    next_cursor = (
        rows[-1].id
        if rows
        else cursor
    )

    return {
        "changes": changes,
        "next_cursor": next_cursor,
        "has_more": len(rows) == limit,
    }


# ============================================================
# SYNC STATUS
# ============================================================

@router.get("/status")
def status(
    company_id: int = Query(...),
    cursor: int = Query(
        0,
        ge=0,
    ),
    device_id: str = Query(""),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """
    Number of changes from OTHER devices that this device
    has not pulled yet.
    """

    require_company_access(
        company_id,
        db,
        user,
    )

    n = (
        db.query(
            func.count(
                transactions.SyncChange.id
            )
        )
        .filter(
            transactions.SyncChange.company_id
            == company_id,

            transactions.SyncChange.id
            > cursor,

            transactions.SyncChange.device_id
            != device_id,
        )
        .scalar()
    )

    return {
        "pending_pull": int(n or 0)
    }


# ============================================================
# LEGACY TABLE PULL
# ============================================================

@router.get(
    "/pull-table",
    deprecated=True,
)
def pull_table(
    table: str = Query(...),
    since: str = Query(...),
    company_id: int = Query(...),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """
    Legacy timestamp-based pull.

    Keep only for older clients.

    New clients should use /sync/pull.
    """

    require_company_access(
        company_id,
        db,
        user,
    )

    model = _TABLE_MODELS.get(table)

    if not model:
        return {
            "rows": []
        }

    since_dt = _parse_dt(since)

    query = (
        db.query(model)
        .filter(
            model.updated_at
            > since_dt
        )
    )

    if hasattr(model, "company_id"):
        query = query.filter(
            model.company_id
            == company_id
        )

    rows = query.all()

    out = []

    for row_obj in rows:

        row = {
            c.name: getattr(
                row_obj,
                c.name,
            )
            for c in model.__table__.columns
        }

        # Convert internal FK IDs back to UUIDs.
        for fk_col, fk_model in _FK_MAP.items():

            if fk_col in row:

                uuid_key = (
                    fk_col.replace(
                        "_id",
                        "_uuid",
                    )
                )

                row[uuid_key] = _uuid_of(
                    db,
                    fk_model,
                    row.pop(fk_col),
                )

        # Database internal ID must never
        # be exposed as the portable identity.
        row.pop("id", None)

        out.append(row)

    return {
        "rows": out,
        "server_time": datetime.now(
            timezone.utc
        ).isoformat(),
    }