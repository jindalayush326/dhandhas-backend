"""financial integrity: check constraints on amounts/dr_cr, report index

Revision ID: 0005
Revises: 0004
"""
import sqlalchemy as sa
from alembic import op

revision = "0005"
down_revision = "0004"


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    is_postgres = bind.dialect.name == "postgresql"

    existing_idx = {ix["name"] for ix in inspector.get_indexes("vouchers")}
    if "ix_vouchers_company_date" not in existing_idx:
        op.create_index("ix_vouchers_company_date", "vouchers", ["company_id", "voucher_date"])

    if is_postgres:
        ve_checks = {c["name"] for c in inspector.get_check_constraints("voucher_entries")}
        if "ck_voucher_entries_dr_cr" not in ve_checks:
            op.create_check_constraint("ck_voucher_entries_dr_cr", "voucher_entries", "dr_cr IN ('dr','cr')")
        if "ck_voucher_entries_amount_nonneg" not in ve_checks:
            op.create_check_constraint("ck_voucher_entries_amount_nonneg", "voucher_entries", "amount >= 0")

        acc_checks = {c["name"] for c in inspector.get_check_constraints("accounts")}
        if "ck_accounts_ob_type" not in acc_checks:
            op.create_check_constraint("ck_accounts_ob_type", "accounts", "opening_balance_type IN ('dr','cr')")
        if "ck_accounts_ob_nonneg" not in acc_checks:
            op.create_check_constraint("ck_accounts_ob_nonneg", "accounts", "opening_balance >= 0")


def downgrade():
    bind = op.get_bind()
    is_postgres = bind.dialect.name == "postgresql"
    if is_postgres:
        op.drop_constraint("ck_accounts_ob_nonneg", "accounts", type_="check")
        op.drop_constraint("ck_accounts_ob_type", "accounts", type_="check")
        op.drop_constraint("ck_voucher_entries_amount_nonneg", "voucher_entries", type_="check")
        op.drop_constraint("ck_voucher_entries_dr_cr", "voucher_entries", type_="check")
    op.drop_index("ix_vouchers_company_date", table_name="vouchers")
