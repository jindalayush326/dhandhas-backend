from datetime import datetime

from pydantic import BaseModel, EmailStr, Field

from app.schemas.common import SyncFields


class InvitationCreate(BaseModel):
    email: EmailStr
    name: str = ""
    role: str = Field(default="employee")  # admin|accountant|employee|viewer
    permissions: list[str] | None = None
    temp_password: str | None = Field(default=None, min_length=8)
    expiry_days: int | None = Field(default=None, ge=1, le=90)


class InvitationRead(SyncFields):
    email: str
    name: str
    role: str
    status: str
    expires_at: datetime
    accepted_at: datetime | None = None


class InvitationCreateResponse(BaseModel):
    invitation: InvitationRead
    invite_link: str
    temp_password: str


class InvitationAccept(BaseModel):
    token: str
    new_password: str = Field(min_length=8)


class MemberRead(BaseModel):
    id: int
    user_id: int
    email: str
    full_name: str
    role: str
    permissions: list[str] | None = None
    is_active: bool


class MemberUpdate(BaseModel):
    role: str | None = None
    permissions: list[str] | None = None
    is_active: bool | None = None
