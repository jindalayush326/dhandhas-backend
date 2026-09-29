"""financial years, sequence-based sync log, idempotent push, remaining indexes

Revision ID: 0006
Revises: 0005
"""
import sqlalchemy as sa
from alembic import op

revision = "0006"
down_revision = "0005"


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    is_postgres = bind.dialect.name == "postgresql"
    existing_tables = inspector.get_table_names()

    # --- financial_years ---
    if "financial_years" not in existing_tables:
        op.create_table(
            "financial_years",
            sa.Column("id", sa.BigInteger(), primary_key=True),
            sa.Column("uuid", sa.String(36), unique=True, index=True, nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
            sa.Column("is_dirty", sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column("company_id", sa.BigInteger(), sa.ForeignKey("companies.id"), index=True, nullable=False),
            sa.Column("name", sa.String(32), nullable=False),
            sa.Column("start_date", sa.DateTime(timezone=True), nullable=False),
            sa.Column("end_date", sa.DateTime(timezone=True), nullable=False),
            sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.UniqueConstraint("company_id", "name", name="uq_financial_years_company_name"),
        )

    # --- vouchers.financial_year_id ---
    voucher_cols = {c["name"] for c in inspector.get_columns("vouchers")}
    if "financial_year_id" not in voucher_cols:
        # Nullable for now — a company with existing vouchers needs a
        # financial_years row created and a one-off backfill UPDATE before
        # this can safely be made NOT NULL. New vouchers created from here
        # on are always assigned one (see accounting_engine.save_voucher).
        op.add_column("vouchers", sa.Column("financial_year_id", sa.BigInteger(), sa.ForeignKey("financial_years.id"), nullable=True))

    existing_idx = {ix["name"] for ix in inspector.get_indexes("vouchers")}
    if "ix_vouchers_financial_year_id" not in existing_idx:
        op.create_index("ix_vouchers_financial_year_id", "vouchers", ["financial_year_id"])
    if "ix_vouchers_company_fy_date" not in existing_idx:
        op.create_index("ix_vouchers_company_fy_date", "vouchers", ["company_id", "financial_year_id", "voucher_date"])
    if "ix_vouchers_company_type_date" not in existing_idx:
        op.create_index("ix_vouchers_company_type_date", "vouchers", ["company_id", "voucher_type_id", "voucher_date"])
    # Superseded by the two composite indexes above; drop only if present.
    if "ix_vouchers_company_date" in existing_idx:
        op.drop_index("ix_vouchers_company_date", table_name="vouchers")

    # --- sync_changes (sequence log) ---
    if "sync_changes" not in existing_tables:
        op.create_table(
            "sync_changes",
            sa.Column("id", sa.BigInteger(), primary_key=True),  # this IS the sequence
            sa.Column("uuid", sa.String(36), unique=True, index=True, nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
            sa.Column("is_dirty", sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column("company_id", sa.BigInteger(), sa.ForeignKey("companies.id"), index=True, nullable=False),
            sa.Column("entity_type", sa.String(64), nullable=False, index=True),
            sa.Column("entity_id", sa.String(36), nullable=False, index=True),
            sa.Column("operation", sa.String(16), nullable=False),
            sa.Column("payload", sa.JSON(), nullable=True),
            sa.Column("changed_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("device_id", sa.String(128), nullable=False, server_default=""),
        )
        op.create_index("ix_sync_changes_company_id_pk", "sync_changes", ["company_id", "id"])

    # --- sync_operations (push idempotency) ---
    if "sync_operations" not in existing_tables:
        op.create_table(
            "sync_operations",
            sa.Column("id", sa.BigInteger(), primary_key=True),
            sa.Column("uuid", sa.String(36), unique=True, index=True, nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
            sa.Column("is_dirty", sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column("operation_id", sa.String(64), unique=True, index=True, nullable=False),
            sa.Column("company_id", sa.BigInteger(), sa.ForeignKey("companies.id"), index=True, nullable=False),
            sa.Column("device_id", sa.String(128), nullable=False, server_default=""),
            sa.Column("result", sa.JSON(), nullable=True),
        )

    # --- remaining indexes from spec section F ---
    ve_idx = {ix["name"] for ix in inspector.get_indexes("voucher_entries")}
    if "ix_voucher_entries_account_voucher" not in ve_idx:
        op.create_index("ix_voucher_entries_account_voucher", "voucher_entries", ["account_id", "voucher_id"])

    items_idx = {ix["name"] for ix in inspector.get_indexes("items")}
    if "ix_items_company_name" not in items_idx:
        op.create_index("ix_items_company_name", "items", ["company_id", "name"])

    accounts_idx = {ix["name"] for ix in inspector.get_indexes("accounts")}
    if "ix_accounts_company_name" not in accounts_idx:
        op.create_index("ix_accounts_company_name", "accounts", ["company_id", "name"])

    # --- strict amount > 0 (was >= 0) — no zero-value ledger lines ---
    if is_postgres:
        ve_checks = {c["name"] for c in inspector.get_check_constraints("voucher_entries")}
        if "ck_voucher_entries_amount_nonneg" in ve_checks:
            op.drop_constraint("ck_voucher_entries_amount_nonneg", "voucher_entries", type_="check")
        if "ck_voucher_entries_amount_positive" not in ve_checks:
            op.create_check_constraint("ck_voucher_entries_amount_positive", "voucher_entries", "amount > 0")


def downgrade():
    bind = op.get_bind()
    is_postgres = bind.dialect.name == "postgresql"
    if is_postgres:
        op.drop_constraint("ck_voucher_entries_amount_positive", "voucher_entries", type_="check")
        op.create_check_constraint("ck_voucher_entries_amount_nonneg", "voucher_entries", "amount >= 0")
    op.drop_index("ix_accounts_company_name", table_name="accounts")
    op.drop_index("ix_items_company_name", table_name="items")
    op.drop_index("ix_voucher_entries_account_voucher", table_name="voucher_entries")
    op.drop_table("sync_operations")
    op.drop_table("sync_changes")
    op.drop_index("ix_vouchers_company_type_date", table_name="vouchers")
    op.drop_index("ix_vouchers_company_fy_date", table_name="vouchers")
    op.drop_index("ix_vouchers_financial_year_id", table_name="vouchers")
    op.drop_column("vouchers", "financial_year_id")
    op.drop_table("financial_years")
