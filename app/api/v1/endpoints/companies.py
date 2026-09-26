from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.deps import get_current_user, get_db, require_company_access
from app.models.core import Company
from app.models.user import CompanyMember, User
from app.repositories.base import Repository
from app.schemas.core import CompanyCreate, CompanyRead

router = APIRouter(prefix="/companies", tags=["Companies"])


@router.post("", response_model=CompanyRead, status_code=201)
def create_company(payload: CompanyCreate, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    company = Repository(db, Company).create(payload.model_dump())
    db.add(CompanyMember(company_id=company.id, user_id=user.id, role="owner"))
    db.commit()
    return company


@router.get("", response_model=list[CompanyRead])
def list_my_companies(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    if user.is_superuser:
        return Repository(db, Company).list(company_id=None)
    ids = [m.company_id for m in db.query(CompanyMember).filter(CompanyMember.user_id == user.id).all()]
    return db.query(Company).filter(Company.id.in_(ids), Company.deleted_at.is_(None)).all()


@router.get("/{company_id}", response_model=CompanyRead)
def get_company(company_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    require_company_access(company_id, db, user)
    return Repository(db, Company).get(company_id)
