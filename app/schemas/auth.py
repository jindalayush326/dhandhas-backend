from pydantic import BaseModel, EmailStr, Field

from app.schemas.common import SyncFields


class UserCreate(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8)
    full_name: str = ""


class UserLogin(BaseModel):
    email: EmailStr
    password: str


class UserRead(SyncFields):
    email: str
    full_name: str
    is_active: bool
    must_reset_password: bool = False


class TokenPair(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    user: UserRead


# Kept for any caller still expecting the old single-token shape.
class Token(TokenPair):
    pass


class RefreshRequest(BaseModel):
    refresh_token: str


class LogoutRequest(BaseModel):
    refresh_token: str


class ChangePasswordRequest(BaseModel):
    old_password: str
    new_password: str = Field(min_length=8)
