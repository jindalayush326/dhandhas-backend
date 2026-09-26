from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel

from app.schemas.common import SyncFields


class CompanyCreate(BaseModel):
    name: str
    gstin: str | None = None
    fy_start: datetime
    base_currency: str = "INR"
    address_json: dict | None = None


class CompanyRead(SyncFields):
    name: str
    gstin: str | None
    fy_start: datetime
    base_currency: str


class AccountGroupCreate(BaseModel):
    company_id: int
    parent_id: int | None = None
    name: str
    nature: str  # asset|liability|equity|income|expense


class AccountGroupRead(SyncFields):
    company_id: int
    parent_id: int | None
    name: str
    nature: str


class AccountCreate(BaseModel):
    company_id: int
    group_id: int
    name: str
    opening_balance_type: str = "dr"
    opening_balance: Decimal = Decimal("0")
    gstin: str | None = None
    contact_json: dict | None = None


class AccountRead(SyncFields):
    company_id: int
    group_id: int
    name: str
    opening_balance_type: str
    opening_balance: Decimal
    gstin: str | None


class GodownCreate(BaseModel):
    company_id: int
    name: str


class GodownRead(SyncFields):
    company_id: int
    name: str


class ItemCreate(BaseModel):
    company_id: int
    name: str
    hsn_code: str | None = None
    unit: str = "NOS"
    gst_rate: Decimal = Decimal("0")
    opening_qty: Decimal = Decimal("0")
    opening_rate: Decimal = Decimal("0")


class ItemRead(SyncFields):
    company_id: int
    name: str
    hsn_code: str | None
    unit: str
    gst_rate: Decimal
    opening_qty: Decimal
    opening_rate: Decimal


class VoucherTypeCreate(BaseModel):
    company_id: int
    name: str
    nature: str
    abbreviation: str = ""


class VoucherTypeRead(SyncFields):
    company_id: int
    name: str
    nature: str
    abbreviation: str
