from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.deps import get_current_user, get_db, require_permission
from app.core.exceptions import ForbiddenError, NotFoundError
from app.models.core import Company
from app.models.user import AuditLog, CompanyMember, User
from app.schemas.auth import UserRead
from app.schemas.invitation import (
    BulkAssignCompaniesRequest,
    CompanyAllocationItem,
    InvitationAccept,
    InvitationCreate,
    InvitationCreateResponse,
    InvitationRead,
    MemberRead,
    MemberUpdate,
    StaffMemberOverview,
)
from app.services import auth_service, invitation_service
from app.services.audit_service import log_audit

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
    user: User = Depends(get_current_user),
    _member=Depends(require_permission("members:invite")),
):
    invitation_service.revoke_invitation(db, company_id, invitation_id, revoked_by=user)
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
    actor: User = Depends(get_current_user),
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
    changes = {
        f: getattr(payload, f)
        for f in ("role", "permissions", "is_active")
        if getattr(payload, f) is not None
    }
    for field, value in changes.items():
        setattr(member, field, value)
    db.add(member)
    db.commit()
    db.refresh(member)
    log_audit(
        db, "member_updated", user_id=actor.id, company_id=company_id,
        meta={"member_id": member_id, **changes}
    )
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
    actor: User = Depends(get_current_user),
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
    log_audit(
        db, "member_removed", user_id=actor.id, company_id=company_id,
        meta={"member_id": member_id}
    )
    return None


@router.get("/audit-logs")
def list_audit_logs(
    company_id: int,
    limit: int = 100,
    db: Session = Depends(get_db),
    _member=Depends(require_permission("members:manage")),
):
    limit = min(limit, 500)
    rows = (
        db.query(AuditLog)
        .filter(AuditLog.company_id == company_id)
        .order_by(AuditLog.created_at.desc())
        .limit(limit)
        .all()
    )
    return [
        {
            "id": r.id, "user_id": r.user_id, "action": r.action, "meta": r.meta,
            "ip_address": r.ip_address, "created_at": r.created_at,
        }
        for r in rows
    ]


# ==============================================================================
# Public (No Auth) Invitation Acceptance Endpoint
# ==============================================================================
public_router = APIRouter(prefix="/invitations", tags=["Members & Invitations"])


@public_router.post("/accept", response_model=UserRead)
def accept_invitation(payload: InvitationAccept, db: Session = Depends(get_db)):
    user = invitation_service.accept_invitation(db, payload.token, payload.new_password)
    return user


# ==============================================================================
# Firm / CA Multi-Company Allocation Router
# ==============================================================================
firm_router = APIRouter(prefix="/firm", tags=["Firm / CA Management"])


def _verify_firm_admin(user: User, db: Session):
    """Verifies that the caller is a firm admin, owner, or superuser."""
    if user.is_superuser:
        return
    is_manager = (
        db.query(CompanyMember)
        .filter(
            CompanyMember.user_id == user.id,
            CompanyMember.role.in_(["owner", "admin"]),
            CompanyMember.is_active.is_(True),
            CompanyMember.deleted_at.is_(None),
        )
        .first()
    )
    if not is_manager:
        raise ForbiddenError("Only firm owners and managers can allocate companies")


@firm_router.get("/staff", response_model=list[StaffMemberOverview])
def list_firm_staff(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Lists all staff members across the firm with the count of active companies assigned to each."""
    _verify_firm_admin(current_user, db)
    users = db.query(User).filter(User.deleted_at.is_(None), User.is_active.is_(True)).all()

    out = []
    for u in users:
        count = (
            db.query(CompanyMember)
            .filter(
                CompanyMember.user_id == u.id,
                CompanyMember.is_active.is_(True),
                CompanyMember.deleted_at.is_(None),
            )
            .count()
        )
        out.append(
            StaffMemberOverview(
                user_id=u.id,
                full_name=u.full_name,
                email=u.email,
                assigned_company_count=count,
            )
        )
    return out


@firm_router.get("/staff/{user_id}/companies", response_model=list[CompanyAllocationItem])
def get_staff_company_allocations(
    user_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Returns all firm companies with is_assigned=True/False so the CA UI can render 100 checkboxes."""
    _verify_firm_admin(current_user, db)

    # 1. Fetch IDs of companies currently assigned to this user
    assigned_ids = {
        m.company_id
        for m in db.query(CompanyMember.company_id)
        .filter(
            CompanyMember.user_id == user_id,
            CompanyMember.is_active.is_(True),
            CompanyMember.deleted_at.is_(None),
        )
        .all()
    }

    # 2. Fetch all manageable companies
    if current_user.is_superuser:
        companies = db.query(Company).filter(Company.deleted_at.is_(None)).order_by(Company.legal_name).all()
    else:
        managed_company_ids = [
            m.company_id
            for m in db.query(CompanyMember.company_id)
            .filter(
                CompanyMember.user_id == current_user.id,
                CompanyMember.role.in_(["owner", "admin"]),
                CompanyMember.is_active.is_(True),
                CompanyMember.deleted_at.is_(None),
            )
            .all()
        ]
        companies = (
            db.query(Company)
            .filter(Company.id.in_(managed_company_ids), Company.deleted_at.is_(None))
            .order_by(Company.legal_name)
            .all()
        )

    return [
        CompanyAllocationItem(
            company_id=c.id,
            legal_name=c.legal_name,
            trade_name=c.trade_name,
            is_assigned=c.id in assigned_ids,
        )
        for c in companies
    ]


@firm_router.post("/staff/allocate")
def bulk_allocate_companies(
    payload: BulkAssignCompaniesRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Saves the 10 selected companies from the CA dashboard for the specified employee."""
    _verify_firm_admin(current_user, db)

    target_user = db.query(User).filter(User.id == payload.user_id, User.deleted_at.is_(None)).first()
    if not target_user:
        raise NotFoundError("Staff user not found")

    selected_ids = set(payload.company_ids)

    # Fetch existing memberships for this user
    existing_memberships = (
        db.query(CompanyMember)
        .filter(CompanyMember.user_id == payload.user_id, CompanyMember.deleted_at.is_(None))
        .all()
    )
    existing_map = {m.company_id: m for m in existing_memberships}

    # 1. Uncheck: Deactivate access for unchecked companies
    for comp_id, member in existing_map.items():
        if comp_id not in selected_ids:
            if member.role == "owner":
                continue  # Never strip ownership role automatically
            member.is_active = False

    # 2. Check: Activate existing or create new CompanyMember rows
    for comp_id in selected_ids:
        if comp_id in existing_map:
            member = existing_map[comp_id]
            member.is_active = True
            member.role = payload.role
            if payload.permissions is not None:
                member.permissions = payload.permissions
        else:
            new_member = CompanyMember(
                company_id=comp_id,
                user_id=payload.user_id,
                role=payload.role,
                permissions=payload.permissions,
                is_active=True,
            )
            db.add(new_member)

    db.commit()
    auth_service.revoke_all_for_user(db, payload.user_id)

    return {
        "status": "success",
        "user_id": payload.user_id,
        "assigned_count": len(selected_ids),
        "message": f"Successfully allocated {len(selected_ids)} companies to {target_user.full_name or target_user.email}",
    }