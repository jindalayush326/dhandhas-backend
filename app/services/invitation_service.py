import logging

from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.exceptions import ConflictError, ForbiddenError, InvitationError, NotFoundError
from app.core.security import (
    generate_opaque_token,
    generate_temp_password,
    hash_password,
    hash_token,
    invite_token_expiry,
)
from app.models.mixins import utcnow
from app.models.user import CompanyMember, Invitation, User

logger = logging.getLogger("dhandas.invitations")



def create_invitation(
    db: Session,
    company_id: int,
    invited_by: User,
    email: str,
    name: str,
    role: str,
    permissions: list[str] | None = None,
    temp_password: str | None = None,
    expiry_days: int | None = None,
    max_members: int = None,
) -> tuple[Invitation, str, str]:
    """Creates (or reuses) the invited user's account with a temp password,
    links them to the company as a pending/active member, and returns
    (invitation, raw_invite_token, temp_password) — the raw token/password
    are shown to the inviter exactly once and never stored in clear text.
    """
    max_members = max_members or settings.max_members_per_company
    email = email.strip().lower()

    active_count = (
        db.query(CompanyMember)
        .filter(CompanyMember.company_id == company_id, CompanyMember.deleted_at.is_(None))
        .count()
    )
    if active_count >= max_members:
        raise InvitationError(f"Company has reached its member limit ({max_members})")

    if role in ("owner",):
        raise ForbiddenError("Cannot invite a member directly as owner")

    user = db.query(User).filter(User.email == email).first()
    temp_password = temp_password or generate_temp_password()

    if user:
        existing = (
            db.query(CompanyMember)
            .filter(CompanyMember.company_id == company_id, CompanyMember.user_id == user.id)
            .first()
        )
        if existing and existing.deleted_at is None:
            raise ConflictError("User is already a member of this company")
    else:
        user = User(
            email=email,
            hashed_password=hash_password(temp_password),
            full_name=name,
            is_active=True,
            must_reset_password=True,
        )
        db.add(user)
        db.flush()  # get user.id without committing yet

    member = CompanyMember(
        company_id=company_id, user_id=user.id, role=role, permissions=permissions, is_active=True,
    )
    db.add(member)

    raw_token, token_hash = generate_opaque_token()
    invitation = Invitation(
        company_id=company_id,
        invited_by_id=invited_by.id,
        email=email,
        name=name,
        role=role,
        permissions=permissions,
        token_hash=token_hash,
        temp_password_hash=hash_password(temp_password),
        status="pending",
        expires_at=invite_token_expiry() if expiry_days is None else utcnow_plus_days(expiry_days),
    )
    db.add(invitation)
    db.commit()
    db.refresh(invitation)

    logger.info(
        "invitation_created company_id=%s invited_by=%s email=%s role=%s",
        company_id, invited_by.id, email, role,
    )
    return invitation, raw_token, temp_password


def utcnow_plus_days(days: int):
    from datetime import timedelta
    return utcnow() + timedelta(days=days)


def invite_link(raw_token: str) -> str:
    return f"{settings.frontend_base_url}/accept-invite?token={raw_token}"


def accept_invitation(db: Session, raw_token: str, new_password: str) -> User:
    token_hash = hash_token(raw_token)
    invitation = db.query(Invitation).filter(Invitation.token_hash == token_hash).first()
    if not invitation:
        raise NotFoundError("Invitation not found")
    if invitation.status == "revoked":
        raise InvitationError("This invitation has been revoked")
    if invitation.status == "accepted":
        raise InvitationError("This invitation has already been accepted")
    if invitation.expires_at < utcnow():
        invitation.status = "expired"
        db.add(invitation)
        db.commit()
        raise InvitationError("This invitation has expired")

    user = db.query(User).filter(User.email == invitation.email).first()
    if not user:
        raise NotFoundError("Invited user account not found")

    user.hashed_password = hash_password(new_password)
    user.must_reset_password = False
    invitation.status = "accepted"
    invitation.accepted_at = utcnow()
    db.add(user)
    db.add(invitation)
    db.commit()
    db.refresh(user)
    logger.info("invitation_accepted invitation_id=%s user_id=%s", invitation.id, user.id)
    return user


def revoke_invitation(db: Session, company_id: int, invitation_id: int) -> None:
    invitation = (
        db.query(Invitation)
        .filter(Invitation.id == invitation_id, Invitation.company_id == company_id)
        .first()
    )
    if not invitation:
        raise NotFoundError("Invitation not found")
    invitation.status = "revoked"
    db.add(invitation)
    db.commit()


def list_invitations(db: Session, company_id: int) -> list[Invitation]:
    return (
        db.query(Invitation)
        .filter(Invitation.company_id == company_id, Invitation.deleted_at.is_(None))
        .order_by(Invitation.created_at.desc())
        .all()
    )
