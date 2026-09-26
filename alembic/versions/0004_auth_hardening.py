"""auth hardening: OTP, audit log, lockout, DB-level constraints

Revision ID: 0004
Revises: 0003
"""
import sqlalchemy as sa
from alembic import op

revision = "0004"
down_revision = "0003"


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    is_postgres = bind.dialect.name == "postgresql"

    user_cols = {c["name"] for c in inspector.get_columns("users")}
    if "email_verified" not in user_cols:
        op.add_column("users", sa.Column("email_verified", sa.Boolean(), server_default=sa.false(), nullable=False))
    if "failed_login_attempts" not in user_cols:
        op.add_column("users", sa.Column("failed_login_attempts", sa.Integer(), server_default="0", nullable=False))
    if "locked_until" not in user_cols:
        op.add_column("users", sa.Column("locked_until", sa.DateTime(timezone=True), nullable=True))

    existing_tables = inspector.get_table_names()

    if "otp_codes" not in existing_tables:
        op.create_table(
            "otp_codes",
            sa.Column("id", sa.BigInteger(), primary_key=True),
            sa.Column("uuid", sa.String(36), unique=True, index=True, nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
            sa.Column("is_dirty", sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column("user_id", sa.BigInteger(), sa.ForeignKey("users.id"), index=True, nullable=False),
            sa.Column("purpose", sa.String(24), nullable=False),
            sa.Column("code_hash", sa.String(64), nullable=False),
            sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        )
        op.create_index("ix_otp_codes_user_purpose", "otp_codes", ["user_id", "purpose"])

    if "audit_logs" not in existing_tables:
        op.create_table(
            "audit_logs",
            sa.Column("id", sa.BigInteger(), primary_key=True),
            sa.Column("uuid", sa.String(36), unique=True, index=True, nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
            sa.Column("is_dirty", sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column("user_id", sa.BigInteger(), sa.ForeignKey("users.id"), nullable=True, index=True),
            sa.Column("company_id", sa.BigInteger(), sa.ForeignKey("companies.id"), nullable=True, index=True),
            sa.Column("action", sa.String(64), nullable=False, index=True),
            sa.Column("meta", sa.JSON(), nullable=True),
            sa.Column("ip_address", sa.String(64), nullable=False, server_default=""),
            sa.Column("user_agent", sa.String(255), nullable=False, server_default=""),
        )
        op.create_index("ix_audit_logs_company_action", "audit_logs", ["company_id", "action"])

    # DB-level guardrails — second line of defense behind Pydantic validation
    existing_ck = {c["name"] for c in inspector.get_check_constraints("company_members")} if is_postgres else set()
    if is_postgres and "ck_company_members_role" not in existing_ck:
        op.create_check_constraint(
            "ck_company_members_role", "company_members",
            "role IN ('owner','admin','accountant','employee','viewer')",
        )
    existing_ck_inv = {c["name"] for c in inspector.get_check_constraints("invitations")} if is_postgres else set()
    if is_postgres and "ck_invitations_role" not in existing_ck_inv:
        op.create_check_constraint(
            "ck_invitations_role", "invitations", "role IN ('admin','accountant','employee','viewer')",
        )

    # Partial unique index: one ACTIVE (non-soft-deleted) membership per
    # (company, user). Postgres-only — SQLite doesn't support this cleanly
    # and app-level checks already cover it there.
    if is_postgres:
        existing_idx = {ix["name"] for ix in inspector.get_indexes("company_members")}
        if "uq_company_members_active" not in existing_idx:
            op.create_index(
                "uq_company_members_active", "company_members", ["company_id", "user_id"],
                unique=True, postgresql_where=sa.text("deleted_at IS NULL"),
            )


def downgrade():
    bind = op.get_bind()
    is_postgres = bind.dialect.name == "postgresql"
    if is_postgres:
        op.drop_index("uq_company_members_active", table_name="company_members")
        op.drop_constraint("ck_invitations_role", "invitations", type_="check")
        op.drop_constraint("ck_company_members_role", "company_members", type_="check")
    op.drop_table("audit_logs")
    op.drop_table("otp_codes")
    op.drop_column("users", "locked_until")
    op.drop_column("users", "failed_login_attempts")
    op.drop_column("users", "email_verified")
