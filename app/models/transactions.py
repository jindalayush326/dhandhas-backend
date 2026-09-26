from decimal import Decimal

from sqlalchemy import Boolean, DateTime, ForeignKey, Numeric, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base
from app.models.mixins import SyncMixin


class Voucher(Base, SyncMixin):
    __tablename__ = "vouchers"
    __table_args__ = (UniqueConstraint("company_id", "voucher_type_id", "voucher_number"),)

    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), index=True)
    voucher_type_id: Mapped[int] = mapped_column(ForeignKey("voucher_types.id"), index=True)
    voucher_number: Mapped[str] = mapped_column(String(64))
    voucher_date: Mapped[object] = mapped_column(DateTime(timezone=True), index=True)
    party_id: Mapped[int | None] = mapped_column(ForeignKey("accounts.id"), nullable=True)
    narration: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    reference_number: Mapped[str | None] = mapped_column(String(128), nullable=True)
    is_cancelled: Mapped[bool] = mapped_column(Boolean, default=False)

    # e-Invoice (IRP) tracking — populated by app.services.einvoice_service
    irn: Mapped[str | None] = mapped_column(String(100), nullable=True, index=True)
    ack_no: Mapped[str | None] = mapped_column(String(50), nullable=True)
    signed_qr_code: Mapped[str | None] = mapped_column(String, nullable=True)


class VoucherEntry(Base, SyncMixin):
    """Double-entry ledger line. The dr==cr invariant per voucher is enforced
    exclusively in app/services/accounting_engine.py — never trusted from a
    client payload."""

    __tablename__ = "voucher_entries"

    voucher_id: Mapped[int] = mapped_column(ForeignKey("vouchers.id"), index=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id"), index=True)
    dr_cr: Mapped[str] = mapped_column(String(2))  # 'dr' | 'cr'
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    item_id: Mapped[int | None] = mapped_column(ForeignKey("items.id"), nullable=True)
    godown_id: Mapped[int | None] = mapped_column(ForeignKey("godowns.id"), nullable=True)
    qty: Mapped[Decimal | None] = mapped_column(Numeric(18, 3), nullable=True)
    rate: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)


class GstTaxLine(Base, SyncMixin):
    __tablename__ = "gst_tax_lines"

    voucher_entry_id: Mapped[int] = mapped_column(ForeignKey("voucher_entries.id"), index=True)
    tax_type: Mapped[str] = mapped_column(String(8))  # cgst|sgst|igst|cess
    rate: Mapped[Decimal] = mapped_column(Numeric(5, 2))
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 2))


class StockLedgerEntry(Base, SyncMixin):
    __tablename__ = "stock_ledger_entries"

    voucher_id: Mapped[int] = mapped_column(ForeignKey("vouchers.id"), index=True)
    item_id: Mapped[int] = mapped_column(ForeignKey("items.id"), index=True)
    godown_id: Mapped[int | None] = mapped_column(ForeignKey("godowns.id"), nullable=True)
    entry_date: Mapped[object] = mapped_column(DateTime(timezone=True), index=True)
    qty_in: Mapped[Decimal] = mapped_column(Numeric(18, 3), default=Decimal("0"))
    qty_out: Mapped[Decimal] = mapped_column(Numeric(18, 3), default=Decimal("0"))
    rate: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=Decimal("0"))
