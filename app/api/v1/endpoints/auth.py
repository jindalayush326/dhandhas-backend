from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.core.deps import get_current_user, get_db
from app.core.exceptions import UnauthorizedError
from app.core.middleware import login_rate_limiter
from app.core.security import decode_access_token, hash_password, verify_password
from app.models.user import User
from app.schemas.auth import (
    ChangePasswordRequest,
    LogoutRequest,
    RefreshRequest,
    TokenPair,
    UserCreate,
    UserLogin,
    UserRead,
)
from app.services import auth_service

router = APIRouter(prefix="/auth", tags=["Auth"])


@router.post("/register", response_model=TokenPair, status_code=201)
def register(payload: UserCreate, request: Request, db: Session = Depends(get_db)):
    user = auth_service.register(db, payload.email, payload.password, payload.full_name)
    access, refresh = auth_service.issue_tokens(db, user, request)
    return TokenPair(access_token=access, refresh_token=refresh, user=UserRead.model_validate(user))


@router.post("/login", response_model=TokenPair)
def login(payload: UserLogin, request: Request, db: Session = Depends(get_db)):
    client_key = f"login:{request.client.host if request.client else 'unknown'}:{payload.email.lower()}"
    if not login_rate_limiter.check(client_key):
        raise UnauthorizedError("Too many login attempts. Try again shortly.")
    user = auth_service.authenticate(db, payload.email, payload.password)
    access, refresh = auth_service.issue_tokens(db, user, request)
    return TokenPair(access_token=access, refresh_token=refresh, user=UserRead.model_validate(user))


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
    return None
