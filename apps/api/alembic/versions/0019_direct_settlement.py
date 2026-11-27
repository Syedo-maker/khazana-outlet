"""Cash on delivery, direct to the brand, and monthly commission invoices.

``brand_policies.settlement_mode`` and ``orders.settlement_mode`` say who
collects the buyer's money. Existing rows stay ``platform``, so nothing that
was already placed changes how it settles. ``commission_invoices`` bills a
brand for the commission on its direct orders, one invoice per month, and
``orders.commission_invoice_id`` marks an order as billed so it is billed once.

Revision ID: 0019
Revises: 0018
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0019"
down_revision: str | None = "0018"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    is_postgres = op.get_bind().dialect.name == "postgresql"

    op.create_table(
        "commission_invoices",
        sa.Column("brand_id", sa.String(length=36), nullable=False),
        sa.Column("number", sa.String(length=32), nullable=False),
        sa.Column("period_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("period_end", sa.DateTime(timezone=True), nullable=False),
        sa.Column("order_count", sa.Integer(), nullable=False),
        sa.Column("sales_pkr", sa.Integer(), nullable=False),
        sa.Column("commission_pkr", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("issued_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("due_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("paid_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("paid_reference", sa.String(length=120), nullable=True),
        sa.Column("recorded_by_user_id", sa.String(length=36), nullable=True),
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "commission_pkr >= 0",
            name=op.f("ck_commission_invoices_commission_invoice_non_negative"),
        ),
        sa.CheckConstraint(
            "order_count > 0", name=op.f("ck_commission_invoices_commission_invoice_has_orders")
        ),
        sa.ForeignKeyConstraint(
            ["brand_id"],
            ["brands.id"],
            name=op.f("fk_commission_invoices_brand_id_brands"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["recorded_by_user_id"],
            ["users.id"],
            name=op.f("fk_commission_invoices_recorded_by_user_id_users"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_commission_invoices")),
        sa.UniqueConstraint("number", name=op.f("uq_commission_invoices_number")),
        sa.UniqueConstraint(
            "brand_id", "period_start", name=op.f("one_commission_invoice_per_month")
        ),
    )
    op.create_index(
        "ix_commission_invoices_brand_status", "commission_invoices", ["brand_id", "status"]
    )

    with op.batch_alter_table("brand_policies") as batch:
        batch.add_column(
            sa.Column(
                "settlement_mode", sa.String(length=32), nullable=False, server_default="platform"
            )
        )

    with op.batch_alter_table("orders") as batch:
        batch.add_column(
            sa.Column(
                "settlement_mode", sa.String(length=32), nullable=False, server_default="platform"
            )
        )
        batch.add_column(sa.Column("commission_due_pkr", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("commission_invoice_id", sa.String(length=36), nullable=True))
        batch.create_foreign_key(
            "fk_orders_commission_invoice_id_commission_invoices",
            "commission_invoices",
            ["commission_invoice_id"],
            ["id"],
            ondelete="RESTRICT",
        )
        batch.create_check_constraint(
            op.f("ck_orders_order_commission_due_non_negative"),
            "commission_due_pkr is null or commission_due_pkr >= 0",
        )
        batch.create_index("ix_orders_commission_invoice", ["commission_invoice_id"])

    if is_postgres:
        op.execute("ALTER TABLE commission_invoices ENABLE ROW LEVEL SECURITY")
        op.execute(
            """
            CREATE POLICY commission_invoices_tenant_isolation ON commission_invoices
            USING (
                current_setting('khazana.role', true) = 'admin'
                OR brand_id = current_setting('khazana.brand_id', true)
            )
            """
        )


def downgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        op.execute(
            "DROP POLICY IF EXISTS commission_invoices_tenant_isolation ON commission_invoices"
        )
    with op.batch_alter_table("orders") as batch:
        batch.drop_index("ix_orders_commission_invoice")
        batch.drop_constraint("ck_orders_order_commission_due_non_negative", type_="check")
        batch.drop_constraint(
            "fk_orders_commission_invoice_id_commission_invoices", type_="foreignkey"
        )
        batch.drop_column("commission_invoice_id")
        batch.drop_column("commission_due_pkr")
        batch.drop_column("settlement_mode")
    with op.batch_alter_table("brand_policies") as batch:
        batch.drop_column("settlement_mode")
    op.drop_index("ix_commission_invoices_brand_status", table_name="commission_invoices")
    op.drop_table("commission_invoices")
