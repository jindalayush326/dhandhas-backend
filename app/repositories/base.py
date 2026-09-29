from datetime import datetime, timezone
from typing import Generic, TypeVar

from sqlalchemy.orm import Session

from app.core.exceptions import ConflictError, NotFoundError

ModelT = TypeVar("ModelT")


class Repository(Generic[ModelT]):
    """One CRUD implementation for every SyncMixin model — company-scoped,
    soft-delete aware, paginated, optimistic-locking aware. Adding a new
    master/entity means adding a model, a schema and one route file; never a
    new copy of these methods."""

    def __init__(self, db: Session, model: type[ModelT]):
        self.db = db
        self.model = model

    def _base_query(self, company_id: int | None):
        q = self.db.query(self.model).filter(self.model.deleted_at.is_(None))
        if company_id is not None and hasattr(self.model, "company_id"):
            q = q.filter(self.model.company_id == company_id)
        return q

    def list(self, company_id: int | None = None, skip: int = 0, limit: int = 100) -> list[ModelT]:
        limit = max(1, min(limit, 500))  # hard cap — never let a client pull an unbounded result set
        return self._base_query(company_id).order_by(self.model.id).offset(skip).limit(limit).all()

    def count(self, company_id: int | None = None) -> int:
        return self._base_query(company_id).count()

    def get(self, obj_id: int, company_id: int | None = None) -> ModelT:
        obj = self._base_query(company_id).filter(self.model.id == obj_id).first()
        if not obj:
            raise NotFoundError(f"{self.model.__tablename__} {obj_id} not found")
        return obj

    def create(self, data: dict) -> ModelT:
        obj = self.model(**data)
        self.db.add(obj)
        self.db.commit()
        self.db.refresh(obj)
        return obj

    def update(self, obj_id: int, data: dict, company_id: int | None = None, expected_version: int | None = None) -> ModelT:
        """If `expected_version` is given (the version the client last saw —
        e.g. an offline-sync client), rejects the write with 409 when
        another writer has already changed the row since. Prevents silent
        lost updates instead of last-write-wins clobbering someone's edit."""
        obj = self.get(obj_id, company_id)
        if expected_version is not None and obj.version != expected_version:
            raise ConflictError(
                f"{self.model.__tablename__} {obj_id} was modified by someone else "
                f"(expected version {expected_version}, current {obj.version}) — reload and retry"
            )
        for k, v in data.items():
            setattr(obj, k, v)
        obj.version += 1
        obj.is_dirty = True
        self.db.commit()
        self.db.refresh(obj)
        return obj

    def soft_delete(self, obj_id: int, company_id: int | None = None) -> None:
        obj = self.get(obj_id, company_id)
        obj.deleted_at = datetime.now(timezone.utc)
        obj.is_dirty = True
        self.db.commit()
