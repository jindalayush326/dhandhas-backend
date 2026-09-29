from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.deps import get_current_user, get_db, require_company_access
from app.core.exceptions import ValidationError
from app.models.transactions import Voucher
from app.models.user import User
from app.services.einvoice_service import serialize_to_inv01

router = APIRouter(prefix="/einvoice", tags=["e-Invoice"])


@router.post("/serialize")
def convert_to_einvoice(
    company_id: int, voucher_id: int | None = None, voucher_uuid: str | None = None, db: Session = Depends(get_db), user: User = Depends(get_current_user)
):
    """Builds the standard GST INV-01 JSON for a voucher. Submitting it to
    the IRP (NIC/GSP) and storing the returned IRN/QR back on the voucher is
    the next integration step — wire a live client into this function.

    Takes voucher_id + company_id (tenant-checked) and loads the voucher
    server-side, rather than accepting an arbitrary voucher/company JSON
    blob from the client — the previous version had NO ownership check at
    all and would happily serialize whatever the caller typed in, for any
    company."""
    require_company_access(company_id, db, user, "gst:use")
    q = db.query(Voucher).filter(Voucher.company_id == company_id, Voucher.deleted_at.is_(None))
    q = q.filter(Voucher.uuid == voucher_uuid) if voucher_uuid else q.filter(Voucher.id == voucher_id)
    voucher = q.first()
    if not voucher:
        raise ValidationError(f"Voucher {voucher_uuid or voucher_id} not found in company {company_id}")

    voucher_dict = {c.name: getattr(voucher, c.name) for c in voucher.__table__.columns}
    return serialize_to_inv01(voucher_dict, {"company_id": company_id})