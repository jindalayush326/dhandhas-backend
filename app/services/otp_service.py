from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.exceptions import InvitationError, UnauthorizedError
from app.core.security import generate_otp, hash_token, otp_expiry
from app.models.mixins import utcnow
from app.models.user import OTPCode, User
from app.services.email_service import send_otp_email


def issue_otp(db: Session, user: User, purpose: str) -> None:
    """Invalidates any previous unconsumed OTP of the same purpose, creates
    a fresh one, and emails it. Enforces a cooldown so a script can't spam
    the mail server / OTP table."""
    recent = (
        db.query(OTPCode)
        .filter(OTPCode.user_id == user.id, OTPCode.purpose == purpose, OTPCode.consumed_at.is_(None))
        .order_by(OTPCode.created_at.desc())
        .first()
    )
    if recent and (utcnow() - recent.created_at).total_seconds() < settings.otp_resend_cooldown_seconds:
        raise InvitationError("Please wait before requesting another code")

    code = generate_otp(settings.otp_length)
    db.add(OTPCode(
        user_id=user.id, purpose=purpose, code_hash=hash_token(code), expires_at=otp_expiry(),
    ))
    db.commit()
    send_otp_email(user.email, code, purpose)


def verify_otp(db: Session, user: User, purpose: str, code: str) -> None:
    otp = (
        db.query(OTPCode)
        .filter(OTPCode.user_id == user.id, OTPCode.purpose == purpose, OTPCode.consumed_at.is_(None))
        .order_by(OTPCode.created_at.desc())
        .first()
    )
    if not otp:
        raise UnauthorizedError("No pending verification code — request a new one")
    if otp.expires_at < utcnow():
        raise UnauthorizedError("Code expired — request a new one")
    if otp.attempts >= settings.otp_max_attempts:
        raise UnauthorizedError("Too many incorrect attempts — request a new code")

    if hash_token(code) != otp.code_hash:
        otp.attempts += 1
        db.add(otp)
        db.commit()
        raise UnauthorizedError("Incorrect code")

    otp.consumed_at = utcnow()
    db.add(otp)
    db.commit()
