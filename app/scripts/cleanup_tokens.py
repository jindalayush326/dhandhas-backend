"""Run periodically (cron / systemd timer) to keep auth tables lean:
    python -m app.scripts.cleanup_tokens

Deletes refresh tokens expired >7 days ago and marks invitations whose
expiry has passed as 'expired'. Safe to run anytime; does nothing destructive
to active sessions or pending invites still within their window.
"""
import logging
from datetime import timedelta

from app.core.config import settings
from app.db.session import SessionLocal
from app.models.mixins import utcnow
from app.models.user import Invitation, RefreshToken

logger = logging.getLogger("dhandas.cleanup")


def run() -> None:
    db = SessionLocal()
    try:
        cutoff = utcnow() - timedelta(days=settings.refresh_token_cleanup_days)
        deleted = (
            db.query(RefreshToken)
            .filter(RefreshToken.expires_at < cutoff)
            .delete(synchronize_session=False)
        )
        expired = (
            db.query(Invitation)
            .filter(Invitation.status == "pending", Invitation.expires_at < utcnow())
            .update({"status": "expired"}, synchronize_session=False)
        )
        db.commit()
        logger.info("cleanup_done deleted_refresh_tokens=%s expired_invitations=%s", deleted, expired)
    finally:
        db.close()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    run()
