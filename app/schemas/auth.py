from datetime import datetime

from pydantic import BaseModel, EmailStr, Field, field_validator

from app.core.validators import validate_password_strength
from app.schemas.common import SyncFields


class UserCreate(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    full_name: str = ""

    @field_validator("password")
    @classmethod
    def _check_password(cls, v: str) -> str:
        return validate_password_strength(v)


class UserLogin(BaseModel):
    email: EmailStr
    password: str


class UserRead(SyncFields):
    email: str
    full_name: str
    is_active: bool
    email_verified: bool = False
    must_reset_password: bool = False


class TokenPair(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    user: UserRead


class Token(TokenPair):
    pass


class RegisterResponse(BaseModel):
    user: UserRead
    verification_required: bool
    message: str


class RefreshRequest(BaseModel):
    refresh_token: str


class LogoutRequest(BaseModel):
    refresh_token: str


class ChangePasswordRequest(BaseModel):
    old_password: str
    new_password: str = Field(min_length=8, max_length=128)

    @field_validator("new_password")
    @classmethod
    def _check_password(cls, v: str) -> str:
        return validate_password_strength(v)


class SendOTPRequest(BaseModel):
    email: EmailStr
    purpose: str = "signup_verify"  # signup_verify|login_2fa|password_reset


class VerifyOTPRequest(BaseModel):
    email: EmailStr
    code: str = Field(min_length=4, max_length=8)
    purpose: str = "signup_verify"


class SessionRead(BaseModel):
    id: int
    user_agent: str
    ip_address: str
    created_at: datetime
    expires_at: datetime

    class Config:
        from_attributes = True
