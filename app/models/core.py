from decimal import Decimal

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base
from app.models.mixins import SyncMixin


class Company(Base, SyncMixin):
    __tablename__ = "companies"

    name: Mapped[str] = mapped_column(String(255))
    gstin: Mapped[str | None] = mapped_column(String(15), nullable=True)
    fy_start: Mapped[object] = mapped_column(DateTime(timezone=True))
    base_currency: Mapped[str] = mapped_column(String(8), default="INR")
    address_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)


class AccountGroup(Base, SyncMixin):
    __tablename__ = "account_groups"

    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), index=True)
    parent_id: Mapped[int | None] = mapped_column(ForeignKey("account_groups.id"), nullable=True)
    name: Mapped[str] = mapped_column(String(255))
    nature: Mapped[str] = mapped_column(String(16), index=True)  # asset|liability|equity|income|expense
    is_system: Mapped[bool] = mapped_column(Boolean, default=False)


class Account(Base, SyncMixin):
    __tablename__ = "accounts"

    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), index=True)
    group_id: Mapped[int] = mapped_column(ForeignKey("account_groups.id"), index=True)
    name: Mapped[str] = mapped_column(String(255))
    opening_balance_type: Mapped[str] = mapped_column(String(2), default="dr")
    opening_balance: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=Decimal("0"))
    gstin: Mapped[str | None] = mapped_column(String(15), nullable=True)
    contact_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    is_system: Mapped[bool] = mapped_column(Boolean, default=False)


class Godown(Base, SyncMixin):
    __tablename__ = "godowns"

    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), index=True)
    name: Mapped[str] = mapped_column(String(255))


class Item(Base, SyncMixin):
    __tablename__ = "items"

    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), index=True)
    name: Mapped[str] = mapped_column(String(255))
    hsn_code: Mapped[str | None] = mapped_column(String(16), nullable=True)
    unit: Mapped[str] = mapped_column(String(16), default="NOS")
    gst_rate: Mapped[Decimal] = mapped_column(Numeric(5, 2), default=Decimal("0"))
    opening_qty: Mapped[Decimal] = mapped_column(Numeric(18, 3), default=Decimal("0"))
    opening_rate: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=Decimal("0"))


class VoucherType(Base, SyncMixin):
    __tablename__ = "voucher_types"

    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), index=True)
    name: Mapped[str] = mapped_column(String(64))
    nature: Mapped[str] = mapped_column(String(32))
    abbreviation: Mapped[str] = mapped_column(String(8), default="")
