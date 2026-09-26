from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.deps import get_current_user, get_db, require_company_access
from app.models.transactions import Voucher
from app.models.user import User
from app.repositories.base import Repository
from app.schemas.voucher import VoucherCreate, VoucherRead
from app.services import accounting_engine as engine

router = APIRouter(prefix="/vouchers", tags=["Vouchers"])


@router.post("", response_model=VoucherRead, status_code=201)
def create_voucher(payload: VoucherCreate, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    require_company_access(payload.company_id, db, user, "vouchers:write")
    voucher = engine.save_voucher(
        db,
        company_id=payload.company_id,
        voucher_type_id=payload.voucher_type_id,
        voucher_number=payload.voucher_number,
        voucher_date=payload.voucher_date,
        party_id=payload.party_id,
        narration=payload.narration,
        reference_number=payload.reference_number,
        lines=[e.model_dump() for e in payload.entries],
    )
    return voucher


@router.get("", response_model=list[VoucherRead])
def list_vouchers(company_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    require_company_access(company_id, db, user, "vouchers:read")
    return Repository(db, Voucher).list(company_id=company_id)


@router.get("/{voucher_id}", response_model=VoucherRead)
def get_voucher(
    voucher_id: int, company_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)
):
    require_company_access(company_id, db, user)
    return Repository(db, Voucher).get(voucher_id, company_id)


@router.post("/{voucher_id}/cancel", status_code=204)
def cancel_voucher(
    voucher_id: int, company_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)
):
    require_company_access(company_id, db, user)
    engine.cancel_voucher(db, company_id, voucher_id)
