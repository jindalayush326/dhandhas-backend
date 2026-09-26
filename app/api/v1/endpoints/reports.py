from datetime import date

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.deps import get_current_user, get_db, require_company_access
from app.models.user import User
from app.services import accounting_engine as engine

router = APIRouter(prefix="/reports", tags=["Reports"])


@router.get("/trial-balance")
def trial_balance(
    company_id: int, as_of: date, db: Session = Depends(get_db), user: User = Depends(get_current_user)
):
    require_company_access(company_id, db, user)
    return {"as_of": as_of, "rows": engine.trial_balance(db, company_id, as_of)}


@router.get("/profit-and-loss")
def profit_and_loss(
    company_id: int,
    date_from: date,
    date_to: date,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    require_company_access(company_id, db, user)
    return engine.profit_and_loss(db, company_id, date_from, date_to)


@router.get("/balance-sheet")
def balance_sheet(
    company_id: int, as_of: date, db: Session = Depends(get_db), user: User = Depends(get_current_user)
):
    require_company_access(company_id, db, user)
    return {"as_of": as_of, **engine.balance_sheet(db, company_id, as_of)}


@router.get("/multi-year-pnl")
def multi_year_pnl(
    company_id: int,
    fy_start_years: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """fy_start_years='2022,2023,2024' -> Apr 1..Mar 31 Indian FY per year."""
    require_company_access(company_id, db, user)
    years = [int(y) for y in fy_start_years.split(",")]
    ranges = [(date(y, 4, 1), date(y + 1, 3, 31)) for y in years]
    return {"years": engine.multi_year_pnl(db, company_id, ranges)}


@router.get("/ledger")
def account_ledger(
    company_id: int,
    account_id: int,
    date_from: date,
    date_to: date,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    require_company_access(company_id, db, user)
    return {"rows": engine.account_ledger(db, company_id, account_id, date_from, date_to)}
