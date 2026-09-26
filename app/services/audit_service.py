from fastapi import Request
from sqlalchemy.orm import Session

from app.models.user import AuditLog


def log_audit(
    db: Session,
    action: str,
    user_id: int | None = None,
    company_id: int | None = None,
    meta: dict | None = None,
    request: Request | None = None,
) -> None:
    """Fire-and-forget audit write. Never raises into the caller's flow —
    an audit-log failure should never break the actual business operation."""
    ip, ua = "", ""
    if request is not None:
        ip = request.client.host if request.client else ""
        ua = request.headers.get("user-agent", "")[:255]
    try:
        db.add(AuditLog(
            user_id=user_id, company_id=company_id, action=action, meta=meta,
            ip_address=ip, user_agent=ua,
        ))
        db.commit()
    except Exception:
        db.rollback()
