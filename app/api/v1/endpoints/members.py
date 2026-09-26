from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.deps import get_current_user, get_db, require_permission
from app.core.exceptions import ForbiddenError, NotFoundError
from app.models.user import CompanyMember, User
from app.schemas.auth import UserRead
from app.schemas.invitation import (
    InvitationAccept,
    InvitationCreate,
    InvitationCreateResponse,
    InvitationRead,
    MemberRead,
    MemberUpdate,
)
from app.services import auth_service, invitation_service

router = APIRouter(prefix="/companies/{company_id}", tags=["Members & Invitations"])


@router.post("/invitations", response_model=InvitationCreateResponse, status_code=201)
def create_invitation(
    company_id: int,
    payload: InvitationCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    _member=Depends(require_permission("members:invite")),
):
    invitation, raw_token, temp_password = invitation_service.create_invitation(
        db, company_id, user, payload.email, payload.name, payload.role,
        payload.permissions, payload.temp_password, payload.expiry_days,
    )
    return InvitationCreateResponse(
        invitation=InvitationRead.model_validate(invitation),
        invite_link=invitation_service.invite_link(raw_token),
        temp_password=temp_password,
    )


@router.get("/invitations", response_model=list[InvitationRead])
def list_invitations(
    company_id: int,
    db: Session = Depends(get_db),
    _member=Depends(require_permission("members:invite")),
):
    return invitation_service.list_invitations(db, company_id)


@router.delete("/invitations/{invitation_id}", status_code=204)
def revoke_invitation(
    company_id: int,
    invitation_id: int,
    db: Session = Depends(get_db),
    _member=Depends(require_permission("members:invite")),
):
    invitation_service.revoke_invitation(db, company_id, invitation_id)
    return None


@router.get("/members", response_model=list[MemberRead])
def list_members(
    company_id: int,
    db: Session = Depends(get_db),
    _member=Depends(require_permission("members:manage")),
):
    rows = (
        db.query(CompanyMember, User)
        .join(User, User.id == CompanyMember.user_id)
        .filter(CompanyMember.company_id == company_id, CompanyMember.deleted_at.is_(None))
        .all()
    )
    return [
        MemberRead(
            id=m.id, user_id=u.id, email=u.email, full_name=u.full_name,
            role=m.role, permissions=m.permissions, is_active=m.is_active,
        )
        for m, u in rows
    ]


@router.patch("/members/{member_id}", response_model=MemberRead)
def update_member(
    company_id: int,
    member_id: int,
    payload: MemberUpdate,
    db: Session = Depends(get_db),
    _member=Depends(require_permission("members:manage")),
):
    member = (
        db.query(CompanyMember)
        .filter(CompanyMember.id == member_id, CompanyMember.company_id == company_id)
        .first()
    )
    if not member:
        raise NotFoundError("Member not found")
    if member.role == "owner":
        raise ForbiddenError("Cannot modify the owner's membership")
    for field in ("role", "permissions", "is_active"):
        value = getattr(payload, field)
        if value is not None:
            setattr(member, field, value)
    db.add(member)
    db.commit()
    db.refresh(member)
    user = db.query(User).filter(User.id == member.user_id).first()
    return MemberRead(
        id=member.id, user_id=user.id, email=user.email, full_name=user.full_name,
        role=member.role, permissions=member.permissions, is_active=member.is_active,
    )


@router.delete("/members/{member_id}", status_code=204)
def remove_member(
    company_id: int,
    member_id: int,
    db: Session = Depends(get_db),
    _member=Depends(require_permission("members:manage")),
):
    member = (
        db.query(CompanyMember)
        .filter(CompanyMember.id == member_id, CompanyMember.company_id == company_id)
        .first()
    )
    if not member:
        raise NotFoundError("Member not found")
    if member.role == "owner":
        raise ForbiddenError("Cannot remove the owner")
    member.is_active = False
    db.add(member)
    db.commit()
    auth_service.revoke_all_for_user(db, member.user_id)
    return None


# Public (no auth) invitation-accept endpoint, mounted separately below.
public_router = APIRouter(prefix="/invitations", tags=["Members & Invitations"])


@public_router.post("/accept", response_model=UserRead)
def accept_invitation(payload: InvitationAccept, db: Session = Depends(get_db)):
    user = invitation_service.accept_invitation(db, payload.token, payload.new_password)
    return user
