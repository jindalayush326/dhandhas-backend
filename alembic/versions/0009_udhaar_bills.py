"""add bill-wise udhaar and bill allocations

Revision ID: 0009
Revises: 0008
"""

import sqlalchemy as sa
from alembic import op


revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    existing_tables = set(inspector.get_table_names())

    # ---------------------------------------------------------
    # bills
    # ---------------------------------------------------------
    if "bills" not in existing_tables:
        op.create_table(
            "bills",

            sa.Column(
                "id",
                sa.BigInteger(),
                primary_key=True,
            ),
            sa.Column(
                "uuid",
                sa.String(36),
                unique=True,
                index=True,
                nullable=False,
            ),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                nullable=False,
            ),
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                nullable=False,
            ),
            sa.Column(
                "deleted_at",
                sa.DateTime(timezone=True),
                nullable=True,
            ),
            sa.Column(
                "version",
                sa.Integer(),
                nullable=False,
                server_default="1",
            ),
            sa.Column(
                "is_dirty",
                sa.Boolean(),
                nullable=False,
                server_default=sa.true(),
            ),

            sa.Column(
                "company_id",
                sa.BigInteger(),
                sa.ForeignKey("companies.id"),
                nullable=False,
            ),

            sa.Column(
                "voucher_id",
                sa.BigInteger(),
                sa.ForeignKey("vouchers.id"),
                nullable=True,
            ),

            sa.Column(
                "party_id",
                sa.BigInteger(),
                sa.ForeignKey("accounts.id"),
                nullable=False,
            ),

            sa.Column(
                "party_name",
                sa.String(255),
                nullable=False,
            ),

            sa.Column(
                "side",
                sa.String(2),
                nullable=False,
            ),

            sa.Column(
                "bill_no",
                sa.String(128),
                nullable=False,
            ),

            sa.Column(
                "bill_date",
                sa.DateTime(timezone=True),
                nullable=False,
            ),

            sa.Column(
                "due_date",
                sa.DateTime(timezone=True),
                nullable=True,
            ),

            sa.Column(
                "original",
                sa.Numeric(18, 2),
                nullable=False,
                server_default="0",
            ),

            sa.Column(
                "outstanding",
                sa.Numeric(18, 2),
                nullable=False,
                server_default="0",
            ),

            sa.Column(
                "status",
                sa.String(8),
                nullable=False,
                server_default="open",
            ),

            sa.CheckConstraint(
                "side IN ('dr', 'cr')",
                name="ck_bills_side",
            ),

            sa.CheckConstraint(
                "original >= 0",
                name="ck_bills_original_nonneg",
            ),

            sa.CheckConstraint(
                "outstanding >= 0",
                name="ck_bills_outstanding_nonneg",
            ),

            sa.CheckConstraint(
                "outstanding <= original",
                name="ck_bills_outstanding_le_original",
            ),

            sa.CheckConstraint(
                "status IN ('open', 'part', 'paid')",
                name="ck_bills_status",
            ),
        )

        op.create_index(
            "ix_bills_company_party",
            "bills",
            ["company_id", "party_id"],
        )

        op.create_index(
            "ix_bills_company_due_date",
            "bills",
            ["company_id", "due_date"],
        )

        op.create_index(
            "ix_bills_company_status",
            "bills",
            ["company_id", "status"],
        )

        op.create_index(
            "ix_bills_company_voucher",
            "bills",
            ["company_id", "voucher_id"],
        )

    # ---------------------------------------------------------
    # bill_allocations
    # ---------------------------------------------------------
    if "bill_allocations" not in existing_tables:
        op.create_table(
            "bill_allocations",

            sa.Column(
                "id",
                sa.BigInteger(),
                primary_key=True,
            ),
            sa.Column(
                "uuid",
                sa.String(36),
                unique=True,
                index=True,
                nullable=False,
            ),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                nullable=False,
            ),
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                nullable=False,
            ),
            sa.Column(
                "deleted_at",
                sa.DateTime(timezone=True),
                nullable=True,
            ),
            sa.Column(
                "version",
                sa.Integer(),
                nullable=False,
                server_default="1",
            ),
            sa.Column(
                "is_dirty",
                sa.Boolean(),
                nullable=False,
                server_default=sa.true(),
            ),

            sa.Column(
                "company_id",
                sa.BigInteger(),
                sa.ForeignKey("companies.id"),
                nullable=False,
            ),

            sa.Column(
                "source_voucher_id",
                sa.BigInteger(),
                sa.ForeignKey("vouchers.id"),
                nullable=True,
            ),

            sa.Column(
                "bill_id",
                sa.BigInteger(),
                sa.ForeignKey("bills.id"),
                nullable=False,
            ),

            sa.Column(
                "party_id",
                sa.BigInteger(),
                sa.ForeignKey("accounts.id"),
                nullable=False,
            ),

            sa.Column(
                "amount",
                sa.Numeric(18, 2),
                nullable=False,
            ),

            sa.Column(
                "alloc_date",
                sa.DateTime(timezone=True),
                nullable=False,
            ),

            sa.Column(
                "source_voucher_uuid",
                sa.String(128),
                nullable=True,
            ),

            sa.CheckConstraint(
                "amount > 0",
                name="ck_bill_allocations_amount_positive",
            ),
        )

        op.create_index(
            "ix_bill_allocations_company_bill",
            "bill_allocations",
            ["company_id", "bill_id"],
        )

        op.create_index(
            "ix_bill_allocations_company_party",
            "bill_allocations",
            ["company_id", "party_id"],
        )

        op.create_index(
            "ix_bill_allocations_company_source",
            "bill_allocations",
            ["company_id", "source_voucher_id"],
        )

        op.create_index(
            "ix_bill_allocations_source_voucher_uuid",
            "bill_allocations",
            ["source_voucher_uuid"],
        )


def downgrade():
    op.drop_index(
        "ix_bill_allocations_source_voucher_uuid",
        table_name="bill_allocations",
    )

    op.drop_index(
        "ix_bill_allocations_company_source",
        table_name="bill_allocations",
    )

    op.drop_index(
        "ix_bill_allocations_company_party",
        table_name="bill_allocations",
    )

    op.drop_index(
        "ix_bill_allocations_company_bill",
        table_name="bill_allocations",
    )

    op.drop_table("bill_allocations")

    op.drop_index(
        "ix_bills_company_voucher",
        table_name="bills",
    )

    op.drop_index(
        "ix_bills_company_status",
        table_name="bills",
    )

    op.drop_index(
        "ix_bills_company_due_date",
        table_name="bills",
    )

    op.drop_index(
        "ix_bills_company_party",
        table_name="bills",
    )

    op.drop_table("bills")