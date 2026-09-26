import logging

from fastapi import Request
from sqlalchemy.orm import Session

from app.core.exceptions import ConflictError, UnauthorizedError
from app.core.security import (
    create_access_token,
    generate_opaque_token,
    hash_password,
    hash_token,
    refresh_token_expiry,
    verify_password,
)
from app.models.mixins import utcnow
from app.models.user import RefreshToken, User

logger = logging.getLogger("dhandas.auth")


def _client_meta(request: Request | None) -> tuple[str, str]:
    if not request:
        return "", ""
    ua = request.headers.get("user-agent", "")[:255]
    ip = request.client.host if request.client else ""
    return ua, ip


def register(db: Session, email: str, password: str, full_name: str) -> User:
    email = email.strip().lower()
    if db.query(User).filter(User.email == email).first():
        raise ConflictError("Email already registered")
    user = User(email=email, hashed_password=hash_password(password), full_name=full_name)
    db.add(user)
    db.commit()
    db.refresh(user)
    logger.info("user_registered user_id=%s email=%s", user.id, user.email)
    return user


def authenticate(db: Session, email: str, password: str) -> User:
    email = email.strip().lower()
    user = db.query(User).filter(User.email == email, User.deleted_at.is_(None)).first()
    if not user or not verify_password(password, user.hashed_password):
        logger.warning("login_failed email=%s", email)
        raise UnauthorizedError("Incorrect email or password")
    if not user.is_active:
        raise UnauthorizedError("Account is deactivated")
    user.last_login_at = utcnow()
    db.add(user)
    db.commit()
    logger.info("login_success user_id=%s", user.id)
    return user


def issue_tokens(db: Session, user: User, request: Request | None = None) -> tuple[str, str]:
    access = create_access_token(subject=str(user.id))
    raw_refresh, refresh_hash = generate_opaque_token()
    ua, ip = _client_meta(request)
    db.add(RefreshToken(
        user_id=user.id, token_hash=refresh_hash, expires_at=refresh_token_expiry(),
        user_agent=ua, ip_address=ip,
    ))
    db.commit()
    return access, raw_refresh


# Backwards-compat single-token helper (used nowhere critical, kept for safety)
def issue_token(user: User) -> str:
    return create_access_token(subject=str(user.id))


def rotate_refresh_token(db: Session, raw_token: str, request: Request | None = None) -> tuple[str, str]:
    token_hash = hash_token(raw_token)
    record = db.query(RefreshToken).filter(RefreshToken.token_hash == token_hash).first()
    if not record or record.revoked_at is not None or record.expires_at < utcnow():
        if record and record.revoked_at is not None:
            # Reuse of a rotated/revoked token: treat as compromise, kill the whole chain.
            logger.warning("refresh_reuse_detected user_id=%s", record.user_id)
            revoke_all_for_user(db, record.user_id)
        raise UnauthorizedError("Invalid or expired refresh token")

    user = db.query(User).filter(User.id == record.user_id, User.deleted_at.is_(None)).first()
    if not user or not user.is_active:
        raise UnauthorizedError("User not found or inactive")

    record.revoked_at = utcnow()
    access = create_access_token(subject=str(user.id))
    raw_new, new_hash = generate_opaque_token()
    record.replaced_by_hash = new_hash
    ua, ip = _client_meta(request)
    db.add(RefreshToken(
        user_id=user.id, token_hash=new_hash, expires_at=refresh_token_expiry(),
        user_agent=ua, ip_address=ip,
    ))
    db.add(record)
    db.commit()
    return access, raw_new


def revoke_refresh_token(db: Session, raw_token: str) -> None:
    token_hash = hash_token(raw_token)
    record = db.query(RefreshToken).filter(RefreshToken.token_hash == token_hash).first()
    if record and record.revoked_at is None:
        record.revoked_at = utcnow()
        db.add(record)
        db.commit()


def revoke_all_for_user(db: Session, user_id: int) -> None:
    db.query(RefreshToken).filter(
        RefreshToken.user_id == user_id, RefreshToken.revoked_at.is_(None)
    ).update({"revoked_at": utcnow()})
    db.commit()
