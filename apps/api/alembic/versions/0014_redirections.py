"""Upcycle and donation partners, redirections, and impact factors.

Revision ID: 0014
Revises: 0013
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import UTC, datetime

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0014"
down_revision: str | None = "0013"
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
    op.create_table(
        "partners",
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("city", sa.String(length=80), nullable=False),
        sa.Column("categories", JSON, nullable=False),
        sa.Column("grades", JSON, nullable=False),
        sa.Column("min_pieces", sa.Integer(), nullable=False),
        sa.Column("max_pieces", sa.Integer(), nullable=True),
        sa.Column("contact_name", sa.String(length=120), nullable=False),
        sa.Column("contact_phone", sa.String(length=20), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("id", sa.String(length=36), nullable=False),
        *_timestamps(),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_partners")),
    )
    op.create_table(
        "redirections",
        sa.Column("lot_id", sa.String(length=36), nullable=False),
        sa.Column("brand_id", sa.String(length=36), nullable=False),
        sa.Column("partner_id", sa.String(length=36), nullable=False),
        sa.Column("route", sa.String(length=16), nullable=False),
        sa.Column("pieces", sa.Integer(), nullable=False),
        sa.Column("price_pkr", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("note", sa.String(length=500), nullable=False),
        sa.Column("collected_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.String(length=36), nullable=False),
        *_timestamps(),
        sa.ForeignKeyConstraint(
            ["lot_id"], ["lots.id"], name=op.f("fk_redirections_lot_id_lots"), ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["brand_id"],
            ["brands.id"],
            name=op.f("fk_redirections_brand_id_brands"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["partner_id"],
            ["partners.id"],
            name=op.f("fk_redirections_partner_id_partners"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_redirections")),
    )
    factors = op.create_table(
        "impact_factors",
        sa.Column("keyword", sa.String(length=40), nullable=False),
        sa.Column("kg_per_piece", sa.Numeric(precision=6, scale=3), nullable=False),
        sa.Column("water_litres_per_kg", sa.Numeric(precision=10, scale=1), nullable=False),
        sa.Column("co2_kg_per_kg", sa.Numeric(precision=6, scale=2), nullable=False),
        sa.Column("source", sa.String(length=300), nullable=False),
        sa.Column("id", sa.String(length=36), nullable=False),
        *_timestamps(),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_impact_factors")),
        sa.UniqueConstraint("keyword", name=op.f("uq_impact_factors_keyword")),
    )
    # Starting factors from common published averages for apparel. An
    # administrator replaces them with better data; reports show which applied.
    now = datetime.now(UTC)
    op.bulk_insert(
        factors,
        [
            {
                "id": str(uuid.uuid4()),
                "keyword": "*",
                "kg_per_piece": 0.35,
                "water_litres_per_kg": 10000,
                "co2_kg_per_kg": 15,
                "source": "Generic garment. Common published averages for cotton apparel.",
                "created_at": now,
                "updated_at": now,
            },
            {
                "id": str(uuid.uuid4()),
                "keyword": "denim",
                "kg_per_piece": 0.65,
                "water_litres_per_kg": 8000,
                "co2_kg_per_kg": 20,
                "source": "Denim. Common published averages.",
                "created_at": now,
                "updated_at": now,
            },
            {
                "id": str(uuid.uuid4()),
                "keyword": "footwear",
                "kg_per_piece": 0.8,
                "water_litres_per_kg": 8000,
                "co2_kg_per_kg": 14,
                "source": "Footwear. Common published averages.",
                "created_at": now,
                "updated_at": now,
            },
            {
                "id": str(uuid.uuid4()),
                "keyword": "lawn",
                "kg_per_piece": 0.3,
                "water_litres_per_kg": 10000,
                "co2_kg_per_kg": 15,
                "source": "Lawn and light cotton. Common published averages.",
                "created_at": now,
                "updated_at": now,
            },
            {
                "id": str(uuid.uuid4()),
                "keyword": "shawl",
                "kg_per_piece": 0.4,
                "water_litres_per_kg": 10000,
                "co2_kg_per_kg": 18,
                "source": "Shawls and knitwear. Common published averages.",
                "created_at": now,
                "updated_at": now,
            },
        ],
    )


def downgrade() -> None:
    op.drop_table("impact_factors")
    op.drop_table("redirections")
    op.drop_table("partners")
