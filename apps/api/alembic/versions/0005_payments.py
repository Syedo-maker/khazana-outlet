"""Payment events, refunds and payout runs.

Revision ID: 0005
Revises: 0004
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _timestamps() -> list[sa.Column[object]]:
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
    with op.batch_alter_table("payments") as batch:
        batch.add_column(
            sa.Column("refunded_pkr", sa.Integer(), nullable=False, server_default="0")
        )
        batch.create_check_constraint(
            op.f("ck_payments_payment_refund_within_amount"),
            "refunded_pkr >= 0 and refunded_pkr <= amount_pkr",
        )
        batch.alter_column("refunded_pkr", server_default=None)

    op.create_index(
        "uq_payments_one_open_per_order",
        "payments",
        ["order_id"],
        unique=True,
        postgresql_where=sa.text("status in ('pending', 'held')"),
        sqlite_where=sa.text("status in ('pending', 'held')"),
    )

    op.create_table(
        "payment_events",
        sa.Column("provider", sa.String(length=40), nullable=False),
        sa.Column("event_id", sa.String(length=120), nullable=False),
        sa.Column("payment_id", sa.String(length=36), nullable=True),
        sa.Column("outcome", sa.String(length=32), nullable=False),
        sa.Column(
            "payload",
            sa.JSON().with_variant(postgresql.JSONB(), "postgresql"),
            nullable=False,
        ),
        sa.Column("id", sa.String(length=36), nullable=False),
        *_timestamps(),
        sa.ForeignKeyConstraint(
            ["payment_id"],
            ["payments.id"],
            name=op.f("fk_payment_events_payment_id_payments"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_payment_events")),
        sa.UniqueConstraint("provider", "event_id", name="one_payment_event_per_provider_id"),
    )
    op.create_index("ix_payment_events_payment", "payment_events", ["payment_id"])

    op.create_table(
        "payout_runs",
        sa.Column("created_by_user_id", sa.String(length=36), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("payout_count", sa.Integer(), nullable=False),
        sa.Column("total_pkr", sa.Integer(), nullable=False),
        sa.Column("reference", sa.String(length=120), nullable=True),
        sa.Column("paid_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.String(length=36), nullable=False),
        *_timestamps(),
        sa.CheckConstraint("payout_count > 0", name=op.f("ck_payout_runs_payout_run_not_empty")),
        sa.CheckConstraint(
            "total_pkr >= 0", name=op.f("ck_payout_runs_payout_run_total_non_negative")
        ),
        sa.ForeignKeyConstraint(
            ["created_by_user_id"],
            ["users.id"],
            name=op.f("fk_payout_runs_created_by_user_id_users"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_payout_runs")),
    )

    with op.batch_alter_table("payouts") as batch:
        batch.add_column(sa.Column("run_id", sa.String(length=36), nullable=True))
        batch.create_foreign_key(
            op.f("fk_payouts_run_id_payout_runs"),
            "payout_runs",
            ["run_id"],
            ["id"],
            ondelete="SET NULL",
        )

    if op.get_bind().dialect.name == "postgresql":
        op.execute(
            """
            CREATE TRIGGER trg_payment_events_append_only
            BEFORE UPDATE OR DELETE ON payment_events
            FOR EACH STATEMENT EXECUTE FUNCTION khazana_reject_mutation()
            """
        )


def downgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        op.execute("DROP TRIGGER IF EXISTS trg_payment_events_append_only ON payment_events")

    with op.batch_alter_table("payouts") as batch:
        batch.drop_constraint(op.f("fk_payouts_run_id_payout_runs"), type_="foreignkey")
        batch.drop_column("run_id")

    op.drop_table("payout_runs")
    op.drop_index("ix_payment_events_payment", table_name="payment_events")
    op.drop_table("payment_events")
    op.drop_index("uq_payments_one_open_per_order", table_name="payments")

    with op.batch_alter_table("payments") as batch:
        batch.drop_constraint(op.f("ck_payments_payment_refund_within_amount"), type_="check")
        batch.drop_column("refunded_pkr")
