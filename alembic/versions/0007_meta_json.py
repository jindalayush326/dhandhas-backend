"""meta_json on vouchers and items (client UI extras for offline sync)

Revision ID: 0007
Revises: 0006
"""
import sqlalchemy as sa
from alembic import op

revision = "0007"
down_revision = "0006"


def upgrade():
    insp = sa.inspect(op.get_bind())
    for t in ("vouchers", "items"):
        if "meta_json" not in [c["name"] for c in insp.get_columns(t)]:
            op.add_column(t, sa.Column("meta_json", sa.JSON(), nullable=True))


def downgrade():
    op.drop_column("items", "meta_json")
    op.drop_column("vouchers", "meta_json")
