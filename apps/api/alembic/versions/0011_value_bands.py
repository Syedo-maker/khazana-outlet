"""Value bands for the bargaining bot and the markdown agent, and negotiations.

The columns are the ones docs/decisions/0001-ai-value-bands.md recorded, plus
bargain_step_percent, because the decision requires the step size to be a
brand policy row as well as the floor.

Revision ID: 0011
Revises: 0010
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0011"
down_revision: str | None = "0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


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
            sa.Column("allow_bargaining", sa.Boolean(), nullable=False, server_default=sa.false())
        )
        batch.add_column(
            sa.Column("bargain_floor_percent", sa.Numeric(precision=5, scale=2), nullable=True)
        )
        batch.add_column(
            sa.Column(
                "bargain_step_percent",
                sa.Numeric(precision=5, scale=2),
                nullable=False,
                server_default="3.00",
            )
        )
        batch.add_column(
            sa.Column(
                "allow_auto_markdown", sa.Boolean(), nullable=False, server_default=sa.false()
            )
        )
        batch.add_column(
            sa.Column(
                "markdown_step_percent",
                sa.Numeric(precision=5, scale=2),
                nullable=False,
                server_default="5.00",
            )
        )
        batch.add_column(
            sa.Column("markdown_interval_days", sa.Integer(), nullable=False, server_default="14")
        )
        batch.add_column(
            sa.Column("markdown_floor_percent", sa.Numeric(precision=5, scale=2), nullable=True)
        )

    # The defaults fill existing rows; the model sets the values from then on,
    # so the server defaults are dropped to keep the schema matching the model.
    with op.batch_alter_table("brand_policies") as batch:
        for column in (
            "allow_bargaining",
            "bargain_step_percent",
            "allow_auto_markdown",
            "markdown_step_percent",
            "markdown_interval_days",
        ):
            batch.alter_column(column, server_default=None)

    with op.batch_alter_table("lots") as batch:
        batch.add_column(sa.Column("bargaining_enabled", sa.Boolean(), nullable=True))
        batch.add_column(sa.Column("auto_markdown_enabled", sa.Boolean(), nullable=True))
        batch.add_column(sa.Column("last_markdown_at", sa.DateTime(timezone=True), nullable=True))

    op.create_table(
        "negotiations",
        sa.Column("lot_id", sa.String(length=36), nullable=False),
        sa.Column("brand_id", sa.String(length=36), nullable=False),
        sa.Column("buyer_user_id", sa.String(length=36), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("pieces", sa.Integer(), nullable=False),
        sa.Column("list_price_pkr", sa.Integer(), nullable=False),
        sa.Column("floor_price_pkr", sa.Integer(), nullable=False),
        sa.Column("step_pkr", sa.Integer(), nullable=False),
        sa.Column("asking_price_pkr", sa.Integer(), nullable=False),
        sa.Column("rounds", sa.Integer(), nullable=False),
        sa.Column("agreed_price_pkr", sa.Integer(), nullable=True),
        sa.Column("agreed_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("order_id", sa.String(length=36), nullable=True),
        sa.Column("id", sa.String(length=36), nullable=False),
        *_timestamps(),
        sa.ForeignKeyConstraint(
            ["lot_id"], ["lots.id"], name=op.f("fk_negotiations_lot_id_lots"), ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["brand_id"],
            ["brands.id"],
            name=op.f("fk_negotiations_brand_id_brands"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["buyer_user_id"],
            ["users.id"],
            name=op.f("fk_negotiations_buyer_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["order_id"],
            ["orders.id"],
            name=op.f("fk_negotiations_order_id_orders"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_negotiations")),
    )
    op.create_table(
        "negotiation_messages",
        sa.Column("negotiation_id", sa.String(length=36), nullable=False),
        sa.Column("brand_id", sa.String(length=36), nullable=False),
        sa.Column("role", sa.String(length=32), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("offer_pkr", sa.Integer(), nullable=True),
        sa.Column("proposed_pkr", sa.Integer(), nullable=True),
        sa.Column("clamped", sa.Boolean(), nullable=False),
        sa.Column("id", sa.String(length=36), nullable=False),
        *_timestamps(),
        sa.ForeignKeyConstraint(
            ["negotiation_id"],
            ["negotiations.id"],
            name=op.f("fk_negotiation_messages_negotiation_id_negotiations"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["brand_id"],
            ["brands.id"],
            name=op.f("fk_negotiation_messages_brand_id_brands"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_negotiation_messages")),
    )


def downgrade() -> None:
    op.drop_table("negotiation_messages")
    op.drop_table("negotiations")
    with op.batch_alter_table("lots") as batch:
        batch.drop_column("last_markdown_at")
        batch.drop_column("auto_markdown_enabled")
        batch.drop_column("bargaining_enabled")
    with op.batch_alter_table("brand_policies") as batch:
        for column in (
            "markdown_floor_percent",
            "markdown_interval_days",
            "markdown_step_percent",
            "allow_auto_markdown",
            "bargain_step_percent",
            "bargain_floor_percent",
            "allow_bargaining",
        ):
            batch.drop_column(column)
