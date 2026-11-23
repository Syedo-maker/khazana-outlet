"""Committee pools, and the brand setting that allows them.

Revision ID: 0010
Revises: 0009
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0010"
down_revision: str | None = "0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

JSON = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")


def _timestamps() -> list[sa.Column[sa.DateTime]]:
    return [
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
    ]


def upgrade() -> None:
    with op.batch_alter_table("brand_policies") as batch:
        batch.add_column(
            sa.Column(
                "allow_pooled_orders",
                sa.Boolean(),
                nullable=False,
                server_default=sa.false(),
            )
        )
    # The default fills existing rows; the model sets the value from then on,
    # so the server default is dropped to keep the schema matching the model.
    with op.batch_alter_table("brand_policies") as batch:
        batch.alter_column("allow_pooled_orders", server_default=None)

    op.create_table(
        "pools",
        sa.Column("lot_id", sa.String(length=36), nullable=False),
        sa.Column("organiser_user_id", sa.String(length=36), nullable=False),
        sa.Column("city", sa.String(length=80), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("closes_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ordered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.String(length=36), nullable=False),
        *_timestamps(),
        sa.ForeignKeyConstraint(
            ["lot_id"], ["lots.id"], name=op.f("fk_pools_lot_id_lots"), ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["organiser_user_id"],
            ["users.id"],
            name=op.f("fk_pools_organiser_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_pools")),
    )
    op.create_index("ix_pools_city_status", "pools", ["city", "status"])

    op.create_table(
        "pool_members",
        sa.Column("pool_id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("requested", JSON, nullable=False),
        sa.Column("allocated", JSON, nullable=True),
        sa.Column("delivery_address", sa.String(length=500), nullable=False),
        sa.Column("delivery_phone", sa.String(length=11), nullable=False),
        sa.Column("payment_method", sa.String(length=32), nullable=False),
        sa.Column("order_id", sa.String(length=36), nullable=True),
        sa.Column("id", sa.String(length=36), nullable=False),
        *_timestamps(),
        sa.ForeignKeyConstraint(
            ["pool_id"],
            ["pools.id"],
            name=op.f("fk_pool_members_pool_id_pools"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_pool_members_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["order_id"],
            ["orders.id"],
            name=op.f("fk_pool_members_order_id_orders"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_pool_members")),
        sa.UniqueConstraint("pool_id", "user_id", name="one_place_per_member"),
    )


def downgrade() -> None:
    op.drop_table("pool_members")
    op.drop_index("ix_pools_city_status", table_name="pools")
    op.drop_table("pools")
    with op.batch_alter_table("brand_policies") as batch:
        batch.drop_column("allow_pooled_orders")
