from datetime import datetime

from sqlalchemy import JSON, Boolean, CheckConstraint, DateTime, ForeignKey, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base
from app.models.mixins import SyncMixin

VALID_ROLES = ("owner", "admin", "accountant", "employee", "viewer")


class User(Base, SyncMixin):
    __tablename__ = "users"

    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    hashed_password: Mapped[str] = mapped_column(String(255))
    full_name: Mapped[str] = mapped_column(String(255), default="")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    is_superuser: Mapped[bool] = mapped_column(Boolean, default=False)
    must_reset_password: Mapped[bool] = mapped_column(Boolean, default=False)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Email verification (OTP based)
    email_verified: Mapped[bool] = mapped_column(Boolean, default=False)

    # Brute-force protection
    failed_login_attempts: Mapped[int] = mapped_column(Integer, default=0)
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class OTPCode(Base, SyncMixin):
    """Short-lived, hashed OTP for email verification / login 2FA.
    Never store the raw 6-digit code — only its SHA-256 hash."""

    __tablename__ = "otp_codes"

    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    purpose: Mapped[str] = mapped_column(String(24))  # signup_verify|login_2fa|password_reset
    code_hash: Mapped[str] = mapped_column(String(64))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)

    __table_args__ = (
        Index("ix_otp_codes_user_purpose", "user_id", "purpose"),
    )


class AuditLog(Base, SyncMixin):
    """Append-only trail of security/business-relevant events. Never updated
    or soft-deleted in practice — write-once. Kept generic (action + json
    metadata) so every part of the app can log to one table instead of each
    module inventing its own audit mechanism."""

    __tablename__ = "audit_logs"

    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)
    company_id: Mapped[int | None] = mapped_column(ForeignKey("companies.id"), nullable=True, index=True)
    action: Mapped[str] = mapped_column(String(64), index=True)
    meta: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    ip_address: Mapped[str] = mapped_column(String(64), default="")
    user_agent: Mapped[str] = mapped_column(String(255), default="")

    __table_args__ = (
        Index("ix_audit_logs_company_action", "company_id", "action"),
    )


class CompanyMember(Base, SyncMixin):
    """Join table: which users can access which company, and at what role.
    Keeps multi-tenant access control in one place (DRY) instead of an
    owner_id column duplicated across tables."""

    __tablename__ = "company_members"

    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    role: Mapped[str] = mapped_column(String(16), default="owner")  # owner|admin|accountant|employee|viewer
    permissions: Mapped[list | None] = mapped_column(JSON, nullable=True)  # extra granular perms, optional overrides
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    __table_args__ = (
        # Speeds up the two hottest queries: "does this user belong to this
        # company" (every request) and "list members of this company".
        Index("ix_company_members_company_user", "company_id", "user_id"),
        CheckConstraint("role IN ('owner','admin','accountant','employee','viewer')", name="ck_company_members_role"),
    )


class RefreshToken(Base, SyncMixin):
    """Opaque, hashed, rotating refresh tokens. Never store the raw token —
    only its SHA-256 hash — so a DB leak doesn't leak usable tokens."""

    __tablename__ = "refresh_tokens"

    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    replaced_by_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    user_agent: Mapped[str] = mapped_column(String(255), default="")
    ip_address: Mapped[str] = mapped_column(String(64), default="")


class Invitation(Base, SyncMixin):
    """A company owner/admin invites a named person by email with a temp
    password, a role and optional extra permissions. The invite link/token
    expires; on first login the invited user must change their password."""

    __tablename__ = "invitations"

    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), index=True)
    invited_by_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    email: Mapped[str] = mapped_column(String(255), index=True)
    name: Mapped[str] = mapped_column(String(255), default="")
    role: Mapped[str] = mapped_column(String(16), default="employee")
    permissions: Mapped[list | None] = mapped_column(JSON, nullable=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    temp_password_hash: Mapped[str] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(String(16), default="pending")  # pending|accepted|expired|revoked
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    max_uses: Mapped[int] = mapped_column(Integer, default=1)

    __table_args__ = (
        Index("ix_invitations_company_status", "company_id", "status"),
        CheckConstraint("role IN ('admin','accountant','employee','viewer')", name="ck_invitations_role"),
    )
