from datetime import datetime, timezone
from typing import Generic, TypeVar

from sqlalchemy.orm import Session

from app.core.exceptions import NotFoundError

ModelT = TypeVar("ModelT")


class Repository(Generic[ModelT]):
    """One CRUD implementation for every SyncMixin model — company-scoped,
    soft-delete aware. Adding a new master/entity means adding a model, a
    schema and one route file; never a new copy of these five methods."""

    def __init__(self, db: Session, model: type[ModelT]):
        self.db = db
        self.model = model

    def _base_query(self, company_id: int | None):
        q = self.db.query(self.model).filter(self.model.deleted_at.is_(None))
        if company_id is not None and hasattr(self.model, "company_id"):
            q = q.filter(self.model.company_id == company_id)
        return q

    def list(self, company_id: int | None = None, skip: int = 0, limit: int = 200) -> list[ModelT]:
        return self._base_query(company_id).offset(skip).limit(limit).all()

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

    def update(self, obj_id: int, data: dict, company_id: int | None = None) -> ModelT:
        obj = self.get(obj_id, company_id)
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
