from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

from app.core.config import settings

_connect_args = {"check_same_thread": False} if settings.database_url.startswith("sqlite") else {}
_pool_kwargs = {} if settings.database_url.startswith("sqlite") else {
    "pool_size": settings.db_pool_size,
    "max_overflow": settings.db_max_overflow,
    "pool_recycle": 1800,  # recycle before typical cloud LB/DB idle-timeout kills the conn
}

engine = create_engine(
    settings.database_url, pool_pre_ping=True, future=True, connect_args=_connect_args, **_pool_kwargs
)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
Base = declarative_base()


def get_db():
    db = SessionLocal()
    try:
        yield db
    except Exception:
        db.rollback()  # never leave a half-written transaction on an unhandled error
        raise
    finally:
        db.close()
