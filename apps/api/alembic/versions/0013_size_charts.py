"""Size charts: the platform standard and each brand's own.

Revision ID: 0013
Revises: 0012
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import UTC, datetime

import sqlalchemy as sa
from alembic import op

revision: str = "0013"
down_revision: str | None = "0012"
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
    standard = op.create_table(
        "standard_sizes",
        sa.Column("audience", sa.String(length=16), nullable=False),
        sa.Column("label", sa.String(length=16), nullable=False),
        sa.Column("chest_min_cm", sa.Numeric(precision=5, scale=1), nullable=True),
        sa.Column("chest_max_cm", sa.Numeric(precision=5, scale=1), nullable=True),
        sa.Column("waist_min_cm", sa.Numeric(precision=5, scale=1), nullable=True),
        sa.Column("waist_max_cm", sa.Numeric(precision=5, scale=1), nullable=True),
        sa.Column("hip_min_cm", sa.Numeric(precision=5, scale=1), nullable=True),
        sa.Column("hip_max_cm", sa.Numeric(precision=5, scale=1), nullable=True),
        sa.Column("id", sa.String(length=36), nullable=False),
        *_timestamps(),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_standard_sizes")),
        sa.UniqueConstraint("audience", "label", name="one_standard_label"),
    )
    op.create_table(
        "size_chart_rows",
        sa.Column("brand_id", sa.String(length=36), nullable=False),
        sa.Column("audience", sa.String(length=16), nullable=False),
        sa.Column("label", sa.String(length=32), nullable=False),
        sa.Column("chest_min_cm", sa.Numeric(precision=5, scale=1), nullable=True),
        sa.Column("chest_max_cm", sa.Numeric(precision=5, scale=1), nullable=True),
        sa.Column("waist_min_cm", sa.Numeric(precision=5, scale=1), nullable=True),
        sa.Column("waist_max_cm", sa.Numeric(precision=5, scale=1), nullable=True),
        sa.Column("hip_min_cm", sa.Numeric(precision=5, scale=1), nullable=True),
        sa.Column("hip_max_cm", sa.Numeric(precision=5, scale=1), nullable=True),
        sa.Column("id", sa.String(length=36), nullable=False),
        *_timestamps(),
        sa.ForeignKeyConstraint(
            ["brand_id"],
            ["brands.id"],
            name=op.f("fk_size_chart_rows_brand_id_brands"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_size_chart_rows")),
        sa.UniqueConstraint("brand_id", "audience", "label", name="one_brand_size_label"),
    )

    # A generic starting standard in centimetres. An administrator replaces it
    # with a measured one; the translation reads whatever is here.
    now = datetime.now(UTC)
    op.bulk_insert(
        standard,
        [
            {
                "id": str(uuid.uuid4()),
                "audience": "women",
                "label": "XS",
                "chest_min_cm": 78,
                "chest_max_cm": 82,
                "waist_min_cm": 62,
                "waist_max_cm": 66,
                "hip_min_cm": 86,
                "hip_max_cm": 90,
                "created_at": now,
                "updated_at": now,
            },
            {
                "id": str(uuid.uuid4()),
                "audience": "women",
                "label": "S",
                "chest_min_cm": 82,
                "chest_max_cm": 87,
                "waist_min_cm": 66,
                "waist_max_cm": 71,
                "hip_min_cm": 90,
                "hip_max_cm": 95,
                "created_at": now,
                "updated_at": now,
            },
            {
                "id": str(uuid.uuid4()),
                "audience": "women",
                "label": "M",
                "chest_min_cm": 87,
                "chest_max_cm": 92,
                "waist_min_cm": 71,
                "waist_max_cm": 76,
                "hip_min_cm": 95,
                "hip_max_cm": 100,
                "created_at": now,
                "updated_at": now,
            },
            {
                "id": str(uuid.uuid4()),
                "audience": "women",
                "label": "L",
                "chest_min_cm": 92,
                "chest_max_cm": 98,
                "waist_min_cm": 76,
                "waist_max_cm": 82,
                "hip_min_cm": 100,
                "hip_max_cm": 106,
                "created_at": now,
                "updated_at": now,
            },
            {
                "id": str(uuid.uuid4()),
                "audience": "women",
                "label": "XL",
                "chest_min_cm": 98,
                "chest_max_cm": 105,
                "waist_min_cm": 82,
                "waist_max_cm": 89,
                "hip_min_cm": 106,
                "hip_max_cm": 113,
                "created_at": now,
                "updated_at": now,
            },
            {
                "id": str(uuid.uuid4()),
                "audience": "women",
                "label": "XXL",
                "chest_min_cm": 105,
                "chest_max_cm": 113,
                "waist_min_cm": 89,
                "waist_max_cm": 97,
                "hip_min_cm": 113,
                "hip_max_cm": 121,
                "created_at": now,
                "updated_at": now,
            },
            {
                "id": str(uuid.uuid4()),
                "audience": "men",
                "label": "XS",
                "chest_min_cm": 84,
                "chest_max_cm": 88,
                "waist_min_cm": 70,
                "waist_max_cm": 74,
                "hip_min_cm": None,
                "hip_max_cm": None,
                "created_at": now,
                "updated_at": now,
            },
            {
                "id": str(uuid.uuid4()),
                "audience": "men",
                "label": "S",
                "chest_min_cm": 88,
                "chest_max_cm": 94,
                "waist_min_cm": 74,
                "waist_max_cm": 80,
                "hip_min_cm": None,
                "hip_max_cm": None,
                "created_at": now,
                "updated_at": now,
            },
            {
                "id": str(uuid.uuid4()),
                "audience": "men",
                "label": "M",
                "chest_min_cm": 94,
                "chest_max_cm": 100,
                "waist_min_cm": 80,
                "waist_max_cm": 86,
                "hip_min_cm": None,
                "hip_max_cm": None,
                "created_at": now,
                "updated_at": now,
            },
            {
                "id": str(uuid.uuid4()),
                "audience": "men",
                "label": "L",
                "chest_min_cm": 100,
                "chest_max_cm": 106,
                "waist_min_cm": 86,
                "waist_max_cm": 92,
                "hip_min_cm": None,
                "hip_max_cm": None,
                "created_at": now,
                "updated_at": now,
            },
            {
                "id": str(uuid.uuid4()),
                "audience": "men",
                "label": "XL",
                "chest_min_cm": 106,
                "chest_max_cm": 112,
                "waist_min_cm": 92,
                "waist_max_cm": 98,
                "hip_min_cm": None,
                "hip_max_cm": None,
                "created_at": now,
                "updated_at": now,
            },
            {
                "id": str(uuid.uuid4()),
                "audience": "men",
                "label": "XXL",
                "chest_min_cm": 112,
                "chest_max_cm": 120,
                "waist_min_cm": 98,
                "waist_max_cm": 106,
                "hip_min_cm": None,
                "hip_max_cm": None,
                "created_at": now,
                "updated_at": now,
            },
        ],
    )


def downgrade() -> None:
    op.drop_table("size_chart_rows")
    op.drop_table("standard_sizes")
