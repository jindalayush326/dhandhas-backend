import uuid as uuid_lib
from datetime import datetime, timezone

from sqlalchemy import BigInteger, Boolean, DateTime, Integer, String
from sqlalchemy.orm import Mapped, mapped_column


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class SyncMixin:
    """Shared by every syncable table (offline-first client <-> server sync).

    `id` is internal/autoincrement, used for fast FK joins on this database
    only. `uuid` is the stable cross-device identity the sync protocol and
    every client key off — never the internal id, which differs per device.
    """

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    uuid: Mapped[str] = mapped_column(String(36), unique=True, index=True, default=lambda: str(uuid_lib.uuid4()))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow, index=True)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    is_dirty: Mapped[bool] = mapped_column(Boolean, default=True)
