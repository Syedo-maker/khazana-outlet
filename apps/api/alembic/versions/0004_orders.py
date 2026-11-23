"""Cart, order lifecycle records, stock reservation and shipping rates.

Revision ID: 0004
Revises: 0003
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import UTC, datetime

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

JSON_TYPE = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")
NEW_BRAND_TABLES = ("order_events", "order_returns")


def _base_columns() -> list[sa.Column[object]]:
    return [
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
    ]


def upgrade() -> None:
    bind = op.get_bind()
    is_postgres = bind.dialect.name == "postgresql"

    with op.batch_alter_table("lots") as batch:
        batch.add_column(
            sa.Column("reserved_pieces", sa.Integer(), nullable=False, server_default="0")
        )
    # Orders placed before reservation existed still hold their stock.
    op.execute(
        """
        UPDATE lots SET reserved_pieces = (
            SELECT COALESCE(SUM(orders.pieces), 0) FROM orders
            WHERE orders.lot_id = lots.id
              AND orders.status NOT IN ('cancelled', 'refunded')
        )
        """
    )
    op.execute(
        "UPDATE lots SET reserved_pieces = total_pieces WHERE reserved_pieces > total_pieces"
    )
    with op.batch_alter_table("lots") as batch:
        batch.create_check_constraint(
            op.f("ck_lots_reserved_within_lot"),
            "reserved_pieces >= 0 and reserved_pieces <= total_pieces",
        )
        batch.alter_column("reserved_pieces", server_default=None)

    with op.batch_alter_table("brand_policies") as batch:
        batch.add_column(
            sa.Column("dispute_window_days", sa.Integer(), nullable=False, server_default="3")
        )
        batch.create_check_constraint(
            op.f("ck_brand_policies_dispute_window_non_negative"), "dispute_window_days >= 0"
        )
        batch.alter_column("dispute_window_days", server_default=None)

    with op.batch_alter_table("orders") as batch:
        batch.add_column(
            sa.Column("rounding_adjustment_pkr", sa.Integer(), nullable=False, server_default="0")
        )
        batch.add_column(
            sa.Column(
                "payment_method",
                sa.String(length=32),
                nullable=False,
                server_default="bank_transfer",
            )
        )
        batch.add_column(sa.Column("delivered_at", sa.DateTime(timezone=True), nullable=True))
        batch.drop_constraint(op.f("ck_orders_order_subtotal_consistent"), type_="check")
        batch.create_check_constraint(
            op.f("ck_orders_order_subtotal_consistent"),
            "subtotal_pkr = pieces * unit_price_pkr + rounding_adjustment_pkr",
        )
        batch.alter_column("rounding_adjustment_pkr", server_default=None)
        batch.alter_column("payment_method", server_default=None)

    op.create_table(
        "order_events",
        sa.Column("order_id", sa.String(length=36), nullable=False),
        sa.Column("brand_id", sa.String(length=36), nullable=False),
        sa.Column("from_status", sa.String(length=32), nullable=True),
        sa.Column("to_status", sa.String(length=32), nullable=False),
        sa.Column("actor_user_id", sa.String(length=36), nullable=True),
        sa.Column("actor_role", sa.String(length=32), nullable=False),
        sa.Column("note", sa.String(length=500), nullable=True),
        *_base_columns(),
        sa.ForeignKeyConstraint(
            ["order_id"],
            ["orders.id"],
            name="fk_order_events_order_id_orders",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["brand_id"],
            ["brands.id"],
            name="fk_order_events_brand_id_brands",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["actor_user_id"],
            ["users.id"],
            name="fk_order_events_actor_user_id_users",
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_order_events"),
    )
    op.create_index("ix_order_events_order", "order_events", ["order_id", "created_at"])

    op.create_table(
        "order_returns",
        sa.Column("order_id", sa.String(length=36), nullable=False),
        sa.Column("brand_id", sa.String(length=36), nullable=False),
        sa.Column("pieces", sa.Integer(), nullable=False),
        sa.Column("reason", sa.String(length=500), nullable=False),
        sa.Column("recorded_by_user_id", sa.String(length=36), nullable=True),
        *_base_columns(),
        sa.CheckConstraint("pieces > 0", name="ck_order_returns_return_pieces_positive"),
        sa.ForeignKeyConstraint(
            ["order_id"],
            ["orders.id"],
            name="fk_order_returns_order_id_orders",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["brand_id"],
            ["brands.id"],
            name="fk_order_returns_brand_id_brands",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["recorded_by_user_id"],
            ["users.id"],
            name="fk_order_returns_recorded_by_user_id_users",
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_order_returns"),
    )
    op.create_index("ix_order_returns_order", "order_returns", ["order_id"])

    op.create_table(
        "cart_items",
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("lot_id", sa.String(length=36), nullable=False),
        sa.Column("whole_lot", sa.Boolean(), nullable=False),
        sa.Column("selection", JSON_TYPE, nullable=True),
        *_base_columns(),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name="fk_cart_items_user_id_users", ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["lot_id"], ["lots.id"], name="fk_cart_items_lot_id_lots", ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name="pk_cart_items"),
        sa.UniqueConstraint("user_id", "lot_id", name="one_cart_item_per_lot"),
    )

    couriers = op.create_table(
        "couriers",
        sa.Column("code", sa.String(length=40), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("is_default", sa.Boolean(), nullable=False),
        *_base_columns(),
        sa.PrimaryKeyConstraint("id", name="pk_couriers"),
        sa.UniqueConstraint("code", name="uq_couriers_code"),
    )
    rates = op.create_table(
        "shipping_rates",
        sa.Column("courier_id", sa.String(length=36), nullable=False),
        sa.Column("origin_city", sa.String(length=80), nullable=True),
        sa.Column("destination_city", sa.String(length=80), nullable=True),
        sa.Column("base_pkr", sa.Integer(), nullable=False),
        sa.Column("per_kg_pkr", sa.Integer(), nullable=False),
        sa.Column("default_piece_grams", sa.Integer(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        *_base_columns(),
        sa.CheckConstraint("base_pkr >= 0", name="ck_shipping_rates_rate_base_non_negative"),
        sa.CheckConstraint("per_kg_pkr >= 0", name="ck_shipping_rates_rate_per_kg_non_negative"),
        sa.CheckConstraint(
            "default_piece_grams > 0", name="ck_shipping_rates_rate_piece_weight_positive"
        ),
        sa.ForeignKeyConstraint(
            ["courier_id"],
            ["couriers.id"],
            name="fk_shipping_rates_courier_id_couriers",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_shipping_rates"),
    )
    op.create_index("ix_shipping_rates_courier", "shipping_rates", ["courier_id"])

    # A working starting point, editable by an admin like any other rate.
    now = datetime.now(UTC)
    courier_id = str(uuid.uuid4())
    op.bulk_insert(
        couriers,
        [
            {
                "id": courier_id,
                "code": "sandbox",
                "name": "Sandbox courier",
                "is_active": True,
                "is_default": True,
                "created_at": now,
                "updated_at": now,
            }
        ],
    )
    op.bulk_insert(
        rates,
        [
            {
                "id": str(uuid.uuid4()),
                "courier_id": courier_id,
                "origin_city": None,
                "destination_city": None,
                "base_pkr": 500,
                "per_kg_pkr": 60,
                "default_piece_grams": 300,
                "is_active": True,
                "created_at": now,
                "updated_at": now,
            }
        ],
    )

    if is_postgres:
        op.execute(
            """
            CREATE TRIGGER trg_order_events_append_only
            BEFORE UPDATE OR DELETE ON order_events
            FOR EACH STATEMENT EXECUTE FUNCTION khazana_reject_mutation()
            """
        )
        for table in NEW_BRAND_TABLES:
            op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
            op.execute(
                f"""
                CREATE POLICY {table}_tenant_isolation ON {table}
                USING (
                    current_setting('khazana.role', true) = 'admin'
                    OR brand_id = current_setting('khazana.brand_id', true)
                )
                """
            )


def downgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        op.execute("DROP TRIGGER IF EXISTS trg_order_events_append_only ON order_events")

    op.drop_index("ix_shipping_rates_courier", table_name="shipping_rates")
    op.drop_table("shipping_rates")
    op.drop_table("couriers")
    op.drop_table("cart_items")
    op.drop_index("ix_order_returns_order", table_name="order_returns")
    op.drop_table("order_returns")
    op.drop_index("ix_order_events_order", table_name="order_events")
    op.drop_table("order_events")

    with op.batch_alter_table("orders") as batch:
        batch.drop_constraint(op.f("ck_orders_order_subtotal_consistent"), type_="check")
        batch.create_check_constraint(
            op.f("ck_orders_order_subtotal_consistent"), "subtotal_pkr = pieces * unit_price_pkr"
        )
        batch.drop_column("delivered_at")
        batch.drop_column("payment_method")
        batch.drop_column("rounding_adjustment_pkr")

    with op.batch_alter_table("brand_policies") as batch:
        batch.drop_constraint(op.f("ck_brand_policies_dispute_window_non_negative"), type_="check")
        batch.drop_column("dispute_window_days")

    with op.batch_alter_table("lots") as batch:
        batch.drop_constraint(op.f("ck_lots_reserved_within_lot"), type_="check")
        batch.drop_column("reserved_pieces")
