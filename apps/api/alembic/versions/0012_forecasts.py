"""Season calendar, demand forecasts, dead stock flags and production warnings.

Revision ID: 0012
Revises: 0011
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import UTC, date, datetime

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0012"
down_revision: str | None = "0011"
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
    events = op.create_table(
        "season_events",
        sa.Column("name", sa.String(length=80), nullable=False),
        sa.Column("starts_on", sa.Date(), nullable=False),
        sa.Column("ends_on", sa.Date(), nullable=False),
        sa.Column("lead_days", sa.Integer(), nullable=False),
        sa.Column("demand_factor", sa.Numeric(precision=4, scale=2), nullable=False),
        sa.Column("keywords", JSON, nullable=False),
        sa.Column("note", sa.String(length=300), nullable=False),
        sa.Column("id", sa.String(length=36), nullable=False),
        *_timestamps(),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_season_events")),
    )
    op.create_table(
        "demand_forecasts",
        sa.Column("category_id", sa.String(length=36), nullable=False),
        sa.Column("city", sa.String(length=80), nullable=False),
        sa.Column("week_start", sa.Date(), nullable=False),
        sa.Column("expected_pieces", sa.Numeric(precision=10, scale=2), nullable=False),
        sa.Column("base_weekly_pieces", sa.Numeric(precision=10, scale=2), nullable=False),
        sa.Column("factor", sa.Numeric(precision=4, scale=2), nullable=False),
        sa.Column("events", JSON, nullable=False),
        sa.Column("computed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", sa.String(length=36), nullable=False),
        *_timestamps(),
        sa.ForeignKeyConstraint(
            ["category_id"],
            ["categories.id"],
            name=op.f("fk_demand_forecasts_category_id_categories"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_demand_forecasts")),
        sa.UniqueConstraint("category_id", "city", "week_start", name="one_forecast_per_week"),
    )
    op.create_table(
        "lot_forecasts",
        sa.Column("lot_id", sa.String(length=36), nullable=False),
        sa.Column("brand_id", sa.String(length=36), nullable=False),
        sa.Column("weekly_pieces", sa.Numeric(precision=10, scale=2), nullable=False),
        sa.Column("weeks_to_clear", sa.Numeric(precision=8, scale=1), nullable=True),
        sa.Column("at_risk", sa.Boolean(), nullable=False),
        sa.Column("reason", sa.String(length=300), nullable=False),
        sa.Column("computed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", sa.String(length=36), nullable=False),
        *_timestamps(),
        sa.ForeignKeyConstraint(
            ["lot_id"], ["lots.id"], name=op.f("fk_lot_forecasts_lot_id_lots"), ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["brand_id"],
            ["brands.id"],
            name=op.f("fk_lot_forecasts_brand_id_brands"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_lot_forecasts")),
        sa.UniqueConstraint("lot_id", name=op.f("uq_lot_forecasts_lot_id")),
    )
    op.create_table(
        "production_warnings",
        sa.Column("brand_id", sa.String(length=36), nullable=False),
        sa.Column("category_id", sa.String(length=36), nullable=False),
        sa.Column("live_pieces", sa.Integer(), nullable=False),
        sa.Column("weekly_demand", sa.Numeric(precision=10, scale=2), nullable=False),
        sa.Column("weeks_of_demand", sa.Numeric(precision=8, scale=1), nullable=True),
        sa.Column("message", sa.String(length=400), nullable=False),
        sa.Column("computed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", sa.String(length=36), nullable=False),
        *_timestamps(),
        sa.ForeignKeyConstraint(
            ["brand_id"],
            ["brands.id"],
            name=op.f("fk_production_warnings_brand_id_brands"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["category_id"],
            ["categories.id"],
            name=op.f("fk_production_warnings_category_id_categories"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_production_warnings")),
    )

    # A starting calendar. Islamic dates are estimates; an administrator
    # corrects them each year once the moon sighting is announced.
    now = datetime.now(UTC)
    op.bulk_insert(
        events,
        [
            {
                "id": str(uuid.uuid4()),
                "name": "Winter",
                "starts_on": date.fromisoformat("2026-11-15"),
                "ends_on": date.fromisoformat("2027-01-31"),
                "lead_days": 21,
                "demand_factor": 1.4,
                "keywords": {"words": ["shawl", "jacket", "sweater", "knit", "winter", "wool"]},
                "note": "Cold months, strongest in the north.",
                "created_at": now,
                "updated_at": now,
            },
            {
                "id": str(uuid.uuid4()),
                "name": "Wedding season",
                "starts_on": date.fromisoformat("2026-11-01"),
                "ends_on": date.fromisoformat("2027-02-28"),
                "lead_days": 21,
                "demand_factor": 1.5,
                "keywords": {
                    "words": ["formal", "bridal", "wedding", "fancy", "jewellery", "footwear"]
                },
                "note": "Peak shaadi months.",
                "created_at": now,
                "updated_at": now,
            },
            {
                "id": str(uuid.uuid4()),
                "name": "Ramzan",
                "starts_on": date.fromisoformat("2027-02-08"),
                "ends_on": date.fromisoformat("2027-03-09"),
                "lead_days": 14,
                "demand_factor": 1.3,
                "keywords": {"words": ["womenswear", "menswear", "kids", "kurta", "kurti"]},
                "note": "Estimated. Dates follow the moon sighting.",
                "created_at": now,
                "updated_at": now,
            },
            {
                "id": str(uuid.uuid4()),
                "name": "Eid ul Fitr",
                "starts_on": date.fromisoformat("2027-03-10"),
                "ends_on": date.fromisoformat("2027-03-12"),
                "lead_days": 30,
                "demand_factor": 2.0,
                "keywords": {
                    "words": [
                        "womenswear",
                        "menswear",
                        "kids",
                        "footwear",
                        "kurta",
                        "kurti",
                        "lawn",
                    ]
                },
                "note": "Estimated. The biggest clothing week of the year.",
                "created_at": now,
                "updated_at": now,
            },
            {
                "id": str(uuid.uuid4()),
                "name": "Summer lawn",
                "starts_on": date.fromisoformat("2027-03-15"),
                "ends_on": date.fromisoformat("2027-06-30"),
                "lead_days": 21,
                "demand_factor": 1.6,
                "keywords": {"words": ["lawn", "summer", "cotton"]},
                "note": "Lawn launches and the summer season.",
                "created_at": now,
                "updated_at": now,
            },
            {
                "id": str(uuid.uuid4()),
                "name": "Eid ul Adha",
                "starts_on": date.fromisoformat("2027-05-16"),
                "ends_on": date.fromisoformat("2027-05-18"),
                "lead_days": 21,
                "demand_factor": 1.5,
                "keywords": {"words": ["womenswear", "menswear", "kids", "footwear"]},
                "note": "Estimated. Dates follow the moon sighting.",
                "created_at": now,
                "updated_at": now,
            },
            {
                "id": str(uuid.uuid4()),
                "name": "Monsoon",
                "starts_on": date.fromisoformat("2027-07-01"),
                "ends_on": date.fromisoformat("2027-09-15"),
                "lead_days": 7,
                "demand_factor": 1.3,
                "keywords": {"words": ["umbrella", "rain", "footwear"]},
                "note": "Rains, strongest in Punjab and Sindh.",
                "created_at": now,
                "updated_at": now,
            },
            {
                "id": str(uuid.uuid4()),
                "name": "School opening",
                "starts_on": date.fromisoformat("2027-08-01"),
                "ends_on": date.fromisoformat("2027-08-31"),
                "lead_days": 21,
                "demand_factor": 1.8,
                "keywords": {"words": ["uniform", "school", "kids", "bag", "shoes"]},
                "note": "New school year.",
                "created_at": now,
                "updated_at": now,
            },
        ],
    )


def downgrade() -> None:
    op.drop_table("production_warnings")
    op.drop_table("lot_forecasts")
    op.drop_table("demand_forecasts")
    op.drop_table("season_events")
