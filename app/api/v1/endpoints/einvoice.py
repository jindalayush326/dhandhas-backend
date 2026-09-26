from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.deps import get_current_user, get_db
from app.models.user import User
from app.services.einvoice_service import serialize_to_inv01

router = APIRouter(prefix="/einvoice", tags=["e-Invoice"])


@router.post("/serialize")
def convert_to_einvoice(payload: dict, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """Builds the standard GST INV-01 JSON for a voucher. Submitting it to
    the IRP (NIC/GSP) and storing the returned IRN/QR back on the voucher is
    the next integration step — wire a live client into this function."""
    voucher = payload.get("voucher", {})
    company = payload.get("company", {})
    return serialize_to_inv01(voucher, company)
