from fastapi import APIRouter, Depends, File, Query, UploadFile
from fastapi.responses import PlainTextResponse, Response
from sqlalchemy.orm import Session

from app.core.deps import get_current_user, get_db, require_permission
from app.core.exceptions import ValidationError
from app.models.user import User
from app.services import import_export
from app.services.audit_service import log_audit

router = APIRouter(prefix="/companies/{company_id}", tags=["Import / Export"])

_MAX_UPLOAD_MB = 25


async def _read_capped(file: UploadFile) -> bytes:
    data = await file.read()
    if len(data) > _MAX_UPLOAD_MB * 1024 * 1024:
        raise ValidationError(f"File too large — max {_MAX_UPLOAD_MB}MB")
    return data


@router.post("/import/tally-xml")
async def import_tally_xml(
    company_id: int,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    _member=Depends(require_permission("masters:write")),
):
    """Import ledgers, stock items, and vouchers from a Tally XML export
    (Gateway of Tally > Export > Data, XML format)."""
    data = await _read_capped(file)
    result = import_export.import_tally_xml(db, company_id, data)
    log_audit(db, "import_tally_xml", user_id=user.id, company_id=company_id,
              meta={"vouchers_imported": result["vouchers_imported"], "error_count": len(result["errors"])})
    return result


@router.post("/import/csv")
async def import_csv(
    company_id: int,
    kind: str = Query(..., pattern="^(ledgers|items|vouchers)$"),
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    _member=Depends(require_permission("masters:write")),
):
    """Import from a CSV (e.g. exported from Busy/Excel/any tool).
    `kind=ledgers` expects columns: name, group, opening_balance, opening_balance_type, gstin
    `kind=items` expects columns: name, hsn_code, unit, gst_rate, opening_qty, opening_rate
    `kind=vouchers` expects one row per ledger entry, columns:
      voucher_number, voucher_type, date, ledger_name, dr_cr, amount, narration
      (rows sharing the same voucher_number become one voucher's entries)
    """
    data = await _read_capped(file)
    text = data.decode("utf-8-sig")  # -sig strips Excel's BOM, a very common source of a broken first column
    fn = {
        "ledgers": import_export.import_csv_ledgers,
        "items": import_export.import_csv_items,
        "vouchers": import_export.import_csv_vouchers,
    }[kind]
    result = fn(db, company_id, text)
    log_audit(db, f"import_csv_{kind}", user_id=user.id, company_id=company_id,
              meta={"error_count": len(result.get("errors", []))})
    return result


@router.get("/export/tally-xml")
def export_tally_xml(
    company_id: int,
    db: Session = Depends(get_db),
    _member=Depends(require_permission("masters:read")),
):
    xml_bytes = import_export.export_tally_xml(db, company_id)
    return Response(
        content=xml_bytes, media_type="application/xml",
        headers={"Content-Disposition": f"attachment; filename=company_{company_id}_export.xml"},
    )


@router.get("/export/csv")
def export_csv(
    company_id: int,
    kind: str = Query(..., pattern="^(ledgers|items|vouchers)$"),
    db: Session = Depends(get_db),
    _member=Depends(require_permission("masters:read")),
):
    fn = {
        "ledgers": import_export.export_csv_ledgers,
        "items": import_export.export_csv_items,
        "vouchers": import_export.export_csv_vouchers,
    }[kind]
    csv_text = fn(db, company_id)
    return PlainTextResponse(
        content=csv_text, media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename={kind}_{company_id}.csv"},
    )
