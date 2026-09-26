from sqlalchemy import create_engine, event
from sqlalchemy.orm import declarative_base, sessionmaker

from app.core.config import settings

_is_sqlite = settings.database_url.startswith("sqlite")
_connect_args = {"check_same_thread": False} if _is_sqlite else {}

_pool_kwargs = {} if _is_sqlite else {"pool_size": settings.db_pool_size, "max_overflow": settings.db_max_overflow}

engine = create_engine(
    settings.database_url,
    pool_pre_ping=True,   # ping each connection before use — required for
                           # Neon/serverless Postgres, which silently closes
                           # idle connections ("SSL connection has been
                           # closed unexpectedly" otherwise).
    pool_recycle=300,     # proactively recycle connections older than 5 min,
                           # well under Neon's idle-close window.
    connect_args=_connect_args,
    future=True,
    **_pool_kwargs,
)

if not _is_sqlite:
    # Statement timeout must be set via `SET` on each new connection, not as
    # a startup/connect_args parameter — poolers like Neon's PgBouncer and
    # Supabase's pooler reject statement_timeout in the startup packet.
    @event.listens_for(engine, "connect")
    def _set_statement_timeout(dbapi_connection, connection_record):
        cursor = dbapi_connection.cursor()
        try:
            cursor.execute(f"SET statement_timeout = {settings.db_statement_timeout_ms}")
            dbapi_connection.commit()
        finally:
            cursor.close()

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