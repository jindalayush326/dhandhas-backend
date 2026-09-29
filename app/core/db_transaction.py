from contextlib import contextmanager

from sqlalchemy.orm import Session


@contextmanager
def db_transaction(db: Session):
    """Wraps a block of multi-step writes as one atomic unit: commits once
    at the end, rolls back the whole thing on any exception. Use this for
    any operation that touches more than one table and must never be left
    half-applied (voucher + entries, bulk import rows, etc).

    Usage:
        with db_transaction(db):
            db.add(a)
            db.flush()
            db.add(b)
        # committed here; rolled back automatically if anything raised
    """
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
