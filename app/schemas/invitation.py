from datetime import datetime
from typing import List, Optional
from pydantic import BaseModel, EmailStr, Field, ConfigDict

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

class CompanyAllocationItem(BaseModel):
    company_id: int
    legal_name: str
    trade_name: Optional[str] = None
    is_assigned: bool


class BulkAssignCompaniesRequest(BaseModel):
    user_id: int
    company_ids: List[int]
    role: str = "accountant"
    permissions: Optional[List[str]] = None


class StaffMemberOverview(BaseModel):
    user_id: int
    full_name: str
    email: str
    assigned_company_count: int

    model_config = ConfigDict(from_attributes=True)