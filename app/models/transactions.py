from decimal import Decimal

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Index, JSON, Numeric, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base
from app.models.mixins import SyncMixin


class Voucher(Base, SyncMixin):
    __tablename__ = "vouchers"
    __table_args__ = (
        Index("ix_vouchers_company_type_number", "company_id", "voucher_type_id", "voucher_number"),
        Index("ix_vouchers_company_fy_date", "company_id", "financial_year_id", "voucher_date"),
        Index("ix_vouchers_company_type_date", "company_id", "voucher_type_id", "voucher_date"),
    )

    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), index=True)
    financial_year_id: Mapped[int] = mapped_column(ForeignKey("financial_years.id"), index=True)
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
    meta_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)  # client UI extras (line items etc.)


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

    __table_args__ = (
        CheckConstraint("dr_cr IN ('dr','cr')", name="ck_voucher_entries_dr_cr"),
        CheckConstraint("amount > 0", name="ck_voucher_entries_amount_positive"),
        Index("ix_voucher_entries_account_voucher", "account_id", "voucher_id"),
    )


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

class Bill(Base, SyncMixin):
    """
    Bill-wise outstanding record.

    Accounting truth remains voucher_entries.
    This table is only for invoice/bill tracking.
    """

    __tablename__ = "bills"

    __table_args__ = (
        CheckConstraint(
            "side IN ('dr', 'cr')",
            name="ck_bills_side",
        ),
        CheckConstraint(
            "original >= 0",
            name="ck_bills_original_nonneg",
        ),
        CheckConstraint(
            "outstanding >= 0",
            name="ck_bills_outstanding_nonneg",
        ),
        CheckConstraint(
            "outstanding <= original",
            name="ck_bills_outstanding_le_original",
        ),
        CheckConstraint(
            "status IN ('open', 'part', 'paid')",
            name="ck_bills_status",
        ),
        Index(
            "ix_bills_company_party",
            "company_id",
            "party_id",
        ),
        Index(
            "ix_bills_company_due_date",
            "company_id",
            "due_date",
        ),
        Index(
            "ix_bills_company_status",
            "company_id",
            "status",
        ),
        Index(
            "ix_bills_company_voucher",
            "company_id",
            "voucher_id",
        ),
    )

    company_id: Mapped[int] = mapped_column(
        ForeignKey("companies.id"),
        index=True,
    )

    # NULL for opening-balance bills.
    voucher_id: Mapped[int | None] = mapped_column(
        ForeignKey("vouchers.id"),
        nullable=True,
        index=True,
    )

    party_id: Mapped[int] = mapped_column(
        ForeignKey("accounts.id"),
        index=True,
    )

    party_name: Mapped[str] = mapped_column(
        String(255),
    )

    # dr = customer receivable / supplier advance
    # cr = supplier payable / customer advance
    side: Mapped[str] = mapped_column(
        String(2),
    )

    bill_no: Mapped[str] = mapped_column(
        String(128),
    )

    bill_date: Mapped[object] = mapped_column(
        DateTime(timezone=True),
        index=True,
    )

    due_date: Mapped[object | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        index=True,
    )

    original: Mapped[Decimal] = mapped_column(
        Numeric(18, 2),
        default=Decimal("0.00"),
    )

    outstanding: Mapped[Decimal] = mapped_column(
        Numeric(18, 2),
        default=Decimal("0.00"),
    )

    status: Mapped[str] = mapped_column(
        String(8),
        default="open",
    )


class BillAllocation(Base, SyncMixin):
    """
    Links a receipt/payment/advance to a bill.

    The source voucher is optional because an opening-balance
    allocation can use source_voucher_uuid = ob_<account_uuid>.
    """

    __tablename__ = "bill_allocations"

    __table_args__ = (
        CheckConstraint(
            "amount > 0",
            name="ck_bill_allocations_amount_positive",
        ),
        Index(
            "ix_bill_allocations_company_bill",
            "company_id",
            "bill_id",
        ),
        Index(
            "ix_bill_allocations_company_party",
            "company_id",
            "party_id",
        ),
        Index(
            "ix_bill_allocations_company_source",
            "company_id",
            "source_voucher_id",
        ),
    )

    company_id: Mapped[int] = mapped_column(
        ForeignKey("companies.id"),
        index=True,
    )

    # NULL for an opening-balance source.
    source_voucher_id: Mapped[int | None] = mapped_column(
        ForeignKey("vouchers.id"),
        nullable=True,
        index=True,
    )

    bill_id: Mapped[int] = mapped_column(
        ForeignKey("bills.id"),
        index=True,
    )

    party_id: Mapped[int] = mapped_column(
        ForeignKey("accounts.id"),
        index=True,
    )

    amount: Mapped[Decimal] = mapped_column(
        Numeric(18, 2),
    )

    alloc_date: Mapped[object] = mapped_column(
        DateTime(timezone=True),
        index=True,
    )

    # For opening-balance allocation:
    # ob_<account_uuid>
    #
    # For normal payment/receipt:
    # UUID of the source voucher.
    source_voucher_uuid: Mapped[str | None] = mapped_column(
        String(128),
        nullable=True,
        index=True,
    )

class SyncChange(Base, SyncMixin):
    """Append-only, server-authoritative change log. `id` (from SyncMixin,
    BIGSERIAL) IS the global monotonic sequence pull cursors are based on —
    a device asks for "everything with id > cursor" and gets an exact,
    ordered, gap-free stream. This is what makes pull reliable, unlike
    `updated_at > timestamp`, which silently misses rows when two changes
    share a timestamp (common with bulk imports) or clocks drift slightly
    across app servers. `payload` is the entity's full state at the moment
    of that change, so a pull can replay changes in order without
    re-querying the live table."""

    __tablename__ = "sync_changes"

    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), index=True)
    entity_type: Mapped[str] = mapped_column(String(64), index=True)
    entity_id: Mapped[str] = mapped_column(String(36), index=True)  # the entity's uuid, not its local id
    operation: Mapped[str] = mapped_column(String(16))  # create|update|delete
    payload: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    changed_at: Mapped[object] = mapped_column(DateTime(timezone=True))
    device_id: Mapped[str] = mapped_column(String(128), default="")

    __table_args__ = (
        Index("ix_sync_changes_company_id_pk", "company_id", "id"),
    )


class SyncOperation(Base, SyncMixin):
    """Idempotency ledger for push requests. Every push carries a client-
    generated `operation_id` (e.g. a UUID the mobile app creates once per
    logical action); if the same operation_id arrives twice — typically a
    retried request after a timeout/network drop where the first attempt
    actually succeeded — the server returns the stored result instead of
    re-applying the changes, so a flaky connection can never create
    duplicate vouchers."""

    __tablename__ = "sync_operations"

    operation_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), index=True)
    device_id: Mapped[str] = mapped_column(String(128), default="")
    result: Mapped[dict | None] = mapped_column(JSON, nullable=True)
