"""Resale benchmarks for the reseller profit helper.

Revision ID: 0008
Revises: 0007
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    table = op.create_table(
        "resale_benchmarks",
        sa.Column("category_id", sa.String(length=36), nullable=True),
        sa.Column("city", sa.String(length=80), nullable=True),
        sa.Column("low_percent", sa.Numeric(precision=5, scale=2), nullable=False),
        sa.Column("typical_percent", sa.Numeric(precision=5, scale=2), nullable=False),
        sa.Column("high_percent", sa.Numeric(precision=5, scale=2), nullable=False),
        sa.Column("note", sa.String(length=300), nullable=False),
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
            "low_percent > 0 AND low_percent <= typical_percent "
            "AND typical_percent <= high_percent AND high_percent <= 100",
            name=op.f("ck_resale_benchmarks_resale_percents_ordered"),
        ),
        sa.ForeignKeyConstraint(
            ["category_id"],
            ["categories.id"],
            name=op.f("fk_resale_benchmarks_category_id_categories"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_resale_benchmarks")),
        # NULLs count as distinct here, so this guards the specific rows; the
        # service reads the fallback row deterministically by creation time.
        sa.UniqueConstraint("category_id", "city", name="one_benchmark_per_category_city"),
    )
    # The fallback row, so an estimate always has an assumption to show. An
    # administrator replaces these numbers with real market data.
    op.bulk_insert(
        table,
        [
            {
                "id": str(uuid.uuid4()),
                "category_id": None,
                "city": None,
                "low_percent": 35,
                "typical_percent": 45,
                "high_percent": 55,
                "note": "Platform default. Replace with market data per category.",
            }
        ],
    )


def downgrade() -> None:
    op.drop_table("resale_benchmarks")
