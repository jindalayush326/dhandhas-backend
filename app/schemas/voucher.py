from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel

from app.schemas.common import SyncFields


class VoucherEntryIn(BaseModel):
    account_id: int
    dr_cr: Literal["dr", "cr"]
    amount: Decimal
    item_id: int | None = None
    godown_id: int | None = None
    qty: Decimal | None = None
    rate: Decimal | None = None


class VoucherCreate(BaseModel):
    company_id: int
    voucher_type_id: int
    voucher_number: str
    voucher_date: datetime
    party_id: int | None = None
    narration: str | None = None
    reference_number: str | None = None
    financial_year_id: int | None = None  # auto-resolved from voucher_date if omitted
    entries: list[VoucherEntryIn]


class VoucherEntryRead(SyncFields):
    account_id: int
    dr_cr: str
    amount: Decimal
    item_id: int | None
    godown_id: int | None
    qty: Decimal | None
    rate: Decimal | None


class VoucherRead(SyncFields):
    company_id: int
    financial_year_id: int
    voucher_type_id: int
    voucher_number: str
    voucher_date: datetime
    party_id: int | None
    narration: str | None
    is_cancelled: bool
    irn: str | None = None
    entries: list[VoucherEntryRead] = []
