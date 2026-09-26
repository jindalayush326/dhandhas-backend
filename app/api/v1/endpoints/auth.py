from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.deps import get_current_user, get_db
from app.core.exceptions import UnauthorizedError
from app.core.middleware import login_rate_limiter
from app.core.security import decode_access_token, hash_password, verify_password
from app.models.user import User
from app.schemas.auth import (
    ChangePasswordRequest,
    LogoutRequest,
    RefreshRequest,
    RegisterResponse,
    SendOTPRequest,
    SessionRead,
    TokenPair,
    UserCreate,
    UserLogin,
    UserRead,
    VerifyOTPRequest,
)
from app.services import auth_service, otp_service
from app.services.audit_service import log_audit

router = APIRouter(prefix="/auth", tags=["Auth"])


def _tokens_response(db: Session, user: User, request: Request) -> TokenPair:
    access, refresh = auth_service.issue_tokens(db, user, request)
    return TokenPair(access_token=access, refresh_token=refresh, user=UserRead.model_validate(user))


@router.post("/register", response_model=RegisterResponse, status_code=201)
def register(payload: UserCreate, request: Request, db: Session = Depends(get_db)):
    user = auth_service.register(db, payload.email, payload.password, payload.full_name, request)
    if settings.require_email_verification:
        return RegisterResponse(
            user=UserRead.model_validate(user),
            verification_required=True,
            message="Account created. Check your email for a verification code.",
        )
    return RegisterResponse(
        user=UserRead.model_validate(user), verification_required=False, message="Account created.",
    )


@router.post("/verify-email", response_model=TokenPair)
def verify_email(payload: VerifyOTPRequest, request: Request, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email == payload.email.lower()).first()
    if not user:
        raise UnauthorizedError("Invalid email or code")
    otp_service.verify_otp(db, user, "signup_verify", payload.code)
    user.email_verified = True
    db.add(user)
    db.commit()
    db.refresh(user)
    log_audit(db, "email_verified", user_id=user.id, request=request)
    return _tokens_response(db, user, request)


@router.post("/resend-otp", status_code=204)
def resend_otp(payload: SendOTPRequest, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email == payload.email.lower()).first()
    if user:  # don't reveal whether an email exists
        otp_service.issue_otp(db, user, payload.purpose)
    return None


@router.post("/login", response_model=TokenPair)
def login(payload: UserLogin, request: Request, db: Session = Depends(get_db)):
    client_key = f"login:{request.client.host if request.client else 'unknown'}:{payload.email.lower()}"
    if not login_rate_limiter.check(client_key):
        raise UnauthorizedError("Too many login attempts. Try again shortly.")
    user = auth_service.authenticate(db, payload.email, payload.password, request)
    return _tokens_response(db, user, request)


@router.post("/refresh", response_model=TokenPair)
def refresh_token(payload: RefreshRequest, request: Request, db: Session = Depends(get_db)):
    access, refresh = auth_service.rotate_refresh_token(db, payload.refresh_token, request)
    user_id = int(decode_access_token(access)["sub"])
    user = db.query(User).filter(User.id == user_id).first()
    return TokenPair(access_token=access, refresh_token=refresh, user=UserRead.model_validate(user))


@router.post("/logout", status_code=204)
def logout(payload: LogoutRequest, db: Session = Depends(get_db)):
    auth_service.revoke_refresh_token(db, payload.refresh_token)
    return None


@router.get("/me", response_model=UserRead)
def me(current_user: User = Depends(get_current_user)):
    return current_user


@router.post("/change-password", status_code=204)
def change_password(
    payload: ChangePasswordRequest,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if not verify_password(payload.old_password, current_user.hashed_password):
        raise UnauthorizedError("Old password is incorrect")
    current_user.hashed_password = hash_password(payload.new_password)
    current_user.must_reset_password = False
    db.add(current_user)
    db.commit()
    auth_service.revoke_all_for_user(db, current_user.id)
    log_audit(db, "password_changed", user_id=current_user.id, request=request)
    return None


# ---- Device / session management ----

@router.get("/sessions", response_model=list[SessionRead])
def list_sessions(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    return auth_service.list_sessions(db, current_user.id)


@router.delete("/sessions/{session_id}", status_code=204)
def revoke_session(
    session_id: int,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    auth_service.revoke_session(db, current_user.id, session_id)
    log_audit(db, "session_revoked", user_id=current_user.id, meta={"session_id": session_id}, request=request)
    return None


@router.delete("/sessions", status_code=204)
def revoke_all_sessions(
    request: Request, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)
):
    auth_service.revoke_all_for_user(db, current_user.id)
    log_audit(db, "all_sessions_revoked", user_id=current_user.id, request=request)
    return None
