"""drop unique(company, voucher_type, voucher_number); add sync_changes device index

Numbers repeat across series and after soft-deletes, so uniqueness here made valid
pushes fail. The app enforces numbering per series locally.

Revision ID: 0008
Revises: 0007
"""
import sqlalchemy as sa
from alembic import op

revision = "0008"
down_revision = "0007"


def upgrade():
    insp = sa.inspect(op.get_bind())
    for uc in insp.get_unique_constraints("vouchers"):
        if set(uc["column_names"]) == {"company_id", "voucher_type_id", "voucher_number"}:
            op.drop_constraint(uc["name"], "vouchers", type_="unique")
    for ix in insp.get_indexes("vouchers"):
        if ix.get("unique") and set(ix["column_names"]) == {"company_id", "voucher_type_id", "voucher_number"}:
            op.drop_index(ix["name"], table_name="vouchers")
    names = {i["name"] for i in sa.inspect(op.get_bind()).get_indexes("vouchers")}
    if "ix_vouchers_company_type_number" not in names:
        op.create_index("ix_vouchers_company_type_number", "vouchers", ["company_id", "voucher_type_id", "voucher_number"])


def downgrade():
    op.drop_index("ix_vouchers_company_type_number", table_name="vouchers")
