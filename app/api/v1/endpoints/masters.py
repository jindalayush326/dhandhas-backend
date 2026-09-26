"""One CRUD router factory reused for every master (account groups, accounts,
items, godowns, voucher types) instead of five near-identical route files."""

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.deps import get_current_user, get_db, require_company_access
from app.models import core as core_models
from app.models.user import User
from app.repositories.base import Repository
from app.schemas import core as core_schemas


def build_master_router(
    model, create_schema: type[BaseModel], read_schema: type[BaseModel], prefix: str, tag: str
) -> APIRouter:
    router = APIRouter(prefix=prefix, tags=[tag])

    @router.get("", response_model=list[read_schema])
    def list_items(
        company_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)
    ):
        require_company_access(company_id, db, user, "masters:read")
        return Repository(db, model).list(company_id=company_id)

    @router.post("", response_model=read_schema, status_code=201)
    def create_item(
        payload: create_schema, db: Session = Depends(get_db), user: User = Depends(get_current_user)
    ):
        require_company_access(payload.company_id, db, user, "masters:write")
        return Repository(db, model).create(payload.model_dump())

    @router.get("/{item_id}", response_model=read_schema)
    def get_item(
        item_id: int, company_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)
    ):
        require_company_access(company_id, db, user, "masters:read")
        return Repository(db, model).get(item_id, company_id)

    @router.put("/{item_id}", response_model=read_schema)
    def update_item(
        item_id: int,
        company_id: int,
        payload: create_schema,
        db: Session = Depends(get_db),
        user: User = Depends(get_current_user),
    ):
        require_company_access(company_id, db, user, "masters:write")
        return Repository(db, model).update(item_id, payload.model_dump(), company_id)

    @router.delete("/{item_id}", status_code=204)
    def delete_item(
        item_id: int, company_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)
    ):
        require_company_access(company_id, db, user, "masters:write")
        Repository(db, model).soft_delete(item_id, company_id)

    return router


account_groups_router = build_master_router(
    core_models.AccountGroup, core_schemas.AccountGroupCreate, core_schemas.AccountGroupRead,
    "/account-groups", "Account Groups",
)
accounts_router = build_master_router(
    core_models.Account, core_schemas.AccountCreate, core_schemas.AccountRead, "/accounts", "Accounts",
)
godowns_router = build_master_router(
    core_models.Godown, core_schemas.GodownCreate, core_schemas.GodownRead, "/godowns", "Godowns",
)
items_router = build_master_router(
    core_models.Item, core_schemas.ItemCreate, core_schemas.ItemRead, "/items", "Items",
)
voucher_types_router = build_master_router(
    core_models.VoucherType, core_schemas.VoucherTypeCreate, core_schemas.VoucherTypeRead,
    "/voucher-types", "Voucher Types",
)

all_master_routers = [
    account_groups_router, accounts_router, godowns_router, items_router, voucher_types_router,
]
