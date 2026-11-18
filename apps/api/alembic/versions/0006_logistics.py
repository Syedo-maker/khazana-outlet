"""Pickup scheduling and shipment tracking events.

Revision ID: 0006
Revises: 0005
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("shipments") as batch:
        batch.add_column(
            sa.Column("pickup_scheduled_for", sa.DateTime(timezone=True), nullable=True)
        )

    op.create_table(
        "shipment_events",
        sa.Column("shipment_id", sa.String(length=36), nullable=False),
        sa.Column("brand_id", sa.String(length=36), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("location", sa.String(length=120), nullable=True),
        sa.Column("note", sa.String(length=300), nullable=True),
        sa.Column("provider_event_id", sa.String(length=120), nullable=True),
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
        sa.ForeignKeyConstraint(
            ["shipment_id"],
            ["shipments.id"],
            name=op.f("fk_shipment_events_shipment_id_shipments"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["brand_id"],
            ["brands.id"],
            name=op.f("fk_shipment_events_brand_id_brands"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_shipment_events")),
        sa.UniqueConstraint(
            "shipment_id", "provider_event_id", name="one_shipment_event_per_provider_id"
        ),
    )
    op.create_index("ix_shipment_events_shipment", "shipment_events", ["shipment_id", "created_at"])

    if op.get_bind().dialect.name == "postgresql":
        op.execute(
            """
            CREATE TRIGGER trg_shipment_events_append_only
            BEFORE UPDATE OR DELETE ON shipment_events
            FOR EACH STATEMENT EXECUTE FUNCTION khazana_reject_mutation()
            """
        )
        op.execute("ALTER TABLE shipment_events ENABLE ROW LEVEL SECURITY")
        op.execute(
            """
            CREATE POLICY shipment_events_tenant_isolation ON shipment_events
            USING (
                current_setting('khazana.role', true) = 'admin'
                OR brand_id = current_setting('khazana.brand_id', true)
            )
            """
        )


def downgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        op.execute("DROP TRIGGER IF EXISTS trg_shipment_events_append_only ON shipment_events")
    op.drop_index("ix_shipment_events_shipment", table_name="shipment_events")
    op.drop_table("shipment_events")
    with op.batch_alter_table("shipments") as batch:
        batch.drop_column("pickup_scheduled_for")
