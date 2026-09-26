"""perf: composite indexes for membership + invitation lookups

Revision ID: 0003
Revises: 0002
"""
import sqlalchemy as sa
from alembic import op

revision = "0003"
down_revision = "0002"


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    existing = {ix["name"] for ix in inspector.get_indexes("company_members")}
    if "ix_company_members_company_user" not in existing:
        op.create_index(
            "ix_company_members_company_user", "company_members", ["company_id", "user_id"]
        )

    existing_inv = {ix["name"] for ix in inspector.get_indexes("invitations")}
    if "ix_invitations_company_status" not in existing_inv:
        op.create_index(
            "ix_invitations_company_status", "invitations", ["company_id", "status"]
        )


def downgrade():
    op.drop_index("ix_invitations_company_status", table_name="invitations")
    op.drop_index("ix_company_members_company_user", table_name="company_members")
