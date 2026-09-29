"""auth: refresh tokens, invitations, rbac columns

Revision ID: 0002
Revises: 0001
"""
import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    user_cols = {c["name"] for c in inspector.get_columns("users")}
    if "must_reset_password" not in user_cols:
        op.add_column("users", sa.Column("must_reset_password", sa.Boolean(), server_default=sa.false(), nullable=False))
    if "last_login_at" not in user_cols:
        op.add_column("users", sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True))

    member_cols = {c["name"] for c in inspector.get_columns("company_members")}
    if "permissions" not in member_cols:
        op.add_column("company_members", sa.Column("permissions", sa.JSON(), nullable=True))
    if "is_active" not in member_cols:
        op.add_column("company_members", sa.Column("is_active", sa.Boolean(), server_default=sa.true(), nullable=False))

    if "refresh_tokens" not in inspector.get_table_names():
        op.create_table(
            "refresh_tokens",
            sa.Column("id", sa.BigInteger(), primary_key=True),
            sa.Column("uuid", sa.String(36), unique=True, index=True, nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
            sa.Column("is_dirty", sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column("user_id", sa.BigInteger(), sa.ForeignKey("users.id"), index=True, nullable=False),
            sa.Column("token_hash", sa.String(64), unique=True, index=True, nullable=False),
            sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("replaced_by_hash", sa.String(64), nullable=True),
            sa.Column("user_agent", sa.String(255), nullable=False, server_default=""),
            sa.Column("ip_address", sa.String(64), nullable=False, server_default=""),
        )

    if "invitations" not in inspector.get_table_names():
        op.create_table(
            "invitations",
            sa.Column("id", sa.BigInteger(), primary_key=True),
            sa.Column("uuid", sa.String(36), unique=True, index=True, nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
            sa.Column("is_dirty", sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column("company_id", sa.BigInteger(), sa.ForeignKey("companies.id"), index=True, nullable=False),
            sa.Column("invited_by_id", sa.BigInteger(), sa.ForeignKey("users.id"), index=True, nullable=False),
            sa.Column("email", sa.String(255), index=True, nullable=False),
            sa.Column("name", sa.String(255), nullable=False, server_default=""),
            sa.Column("role", sa.String(16), nullable=False, server_default="employee"),
            sa.Column("permissions", sa.JSON(), nullable=True),
            sa.Column("token_hash", sa.String(64), unique=True, index=True, nullable=False),
            sa.Column("temp_password_hash", sa.String(255), nullable=False),
            sa.Column("status", sa.String(16), nullable=False, server_default="pending"),
            sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("max_uses", sa.Integer(), nullable=False, server_default="1"),
        )


def downgrade():
    op.drop_table("invitations")
    op.drop_table("refresh_tokens")
    op.drop_column("company_members", "is_active")
    op.drop_column("company_members", "permissions")
    op.drop_column("users", "last_login_at")
    op.drop_column("users", "must_reset_password")