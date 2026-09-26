"""initial schema

Revision ID: 0001
Revises:
"""
from alembic import op
from app.db.session import Base
# Explicitly import all models so SQLAlchemy's Base knows their schemas
import app.models.core  # noqa: F401
import app.models.user  # noqa: F401
import app.models.transactions  # noqa: F401

revision = "0001"
down_revision = None


def upgrade():
    Base.metadata.create_all(bind=op.get_bind())


def downgrade():
    Base.metadata.drop_all(bind=op.get_bind())