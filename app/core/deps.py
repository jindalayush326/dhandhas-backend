from fastapi import Depends, Header
from sqlalchemy.orm import Session

from app.core.exceptions import ForbiddenError, UnauthorizedError
from app.core.rbac import has_permission
from app.core.security import decode_access_token
from app.db.session import get_db
from app.models.user import CompanyMember, User

__all__ = ["get_db"]


def get_current_user(
    authorization: str | None = Header(default=None), db: Session = Depends(get_db)
) -> User:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise UnauthorizedError("Missing bearer token")
    payload = decode_access_token(authorization.split(" ", 1)[1])
    if not payload:
        raise UnauthorizedError("Invalid or expired token")
    user = db.query(User).filter(User.id == int(payload["sub"]), User.deleted_at.is_(None)).first()
    if not user or not user.is_active:
        raise UnauthorizedError("User not found or inactive")
    return user


def get_company_member(company_id: int, db: Session, user: User) -> CompanyMember | None:
    return (
        db.query(CompanyMember)
        .filter(
            CompanyMember.company_id == company_id,
            CompanyMember.user_id == user.id,
            CompanyMember.deleted_at.is_(None),
            CompanyMember.is_active.is_(True),
        )
        .first()
    )


def require_company_access(
    company_id: int, db: Session, user: User, permission: str | None = None
) -> CompanyMember | None:
    """One gate every company-scoped endpoint goes through (DRY tenancy check).
    Pass `permission` to also enforce RBAC in the same call."""
    if user.is_superuser:
        return None
    member = get_company_member(company_id, db, user)
    if not member:
        raise ForbiddenError("You do not have access to this company")
    if permission and not has_permission(member.role, member.permissions, permission):
        raise ForbiddenError(f"Role '{member.role}' lacks permission '{permission}'")
    return member


def require_permission(permission: str):
    """Dependency factory: use as
    `member = Depends(require_permission("vouchers:write"))` on any route
    that has a `company_id` path parameter. Superusers always pass."""

    def _checker(
        company_id: int,
        db: Session = Depends(get_db),
        user: User = Depends(get_current_user),
    ) -> CompanyMember | None:
        if user.is_superuser:
            return None
        member = get_company_member(company_id, db, user)
        if not member:
            raise ForbiddenError("You do not have access to this company")
        if not has_permission(member.role, member.permissions, permission):
            raise ForbiddenError(f"Role '{member.role}' lacks permission '{permission}'")
        return member

    return _checker
