"""Demand forecasts, dead stock flags, over production warnings and seasons.

All of it is written by a scheduled job from sales history and a season
calendar an administrator maintains. None of it is a model's guess: a number
a brand plans production around should come from arithmetic it can check.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, TimestampMixin, UUIDPrimaryKey


class SeasonEvent(UUIDPrimaryKey, TimestampMixin, Base):
    """A season or event that moves demand, such as Eid or school opening.

    Islamic dates follow the moon sighting, so the rows are estimates an
    administrator corrects each year. ``keywords`` are matched against
    category names, so "lawn" lifts every lawn category.
    """

    __tablename__ = "season_events"

    name: Mapped[str] = mapped_column(String(80), nullable=False)
    starts_on: Mapped[date] = mapped_column(Date, nullable=False)
    ends_on: Mapped[date] = mapped_column(Date, nullable=False)
    # Demand starts rising this many days before the event.
    lead_days: Mapped[int] = mapped_column(Integer, nullable=False, default=14)
    demand_factor: Mapped[float] = mapped_column(Numeric(4, 2), nullable=False, default=1.5)
    keywords: Mapped[dict[str, Any]] = mapped_column(nullable=False)
    note: Mapped[str] = mapped_column(String(300), nullable=False, default="")


class DemandForecast(UUIDPrimaryKey, TimestampMixin, Base):
    """Expected pieces sold in one category, one city, one week."""

    __tablename__ = "demand_forecasts"

    category_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("categories.id", ondelete="CASCADE"), nullable=False
    )
    city: Mapped[str] = mapped_column(String(80), nullable=False)
    week_start: Mapped[date] = mapped_column(Date, nullable=False)
    expected_pieces: Mapped[float] = mapped_column(Numeric(10, 2), nullable=False)
    base_weekly_pieces: Mapped[float] = mapped_column(Numeric(10, 2), nullable=False)
    factor: Mapped[float] = mapped_column(Numeric(4, 2), nullable=False, default=1)
    events: Mapped[dict[str, Any]] = mapped_column(nullable=False)
    computed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        UniqueConstraint("category_id", "city", "week_start", name="one_forecast_per_week"),
    )


class LotForecast(UUIDPrimaryKey, TimestampMixin, Base):
    """How long a live lot is likely to take to sell, and whether it is stuck."""

    __tablename__ = "lot_forecasts"

    lot_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("lots.id", ondelete="CASCADE"), nullable=False, unique=True
    )
    brand_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("brands.id", ondelete="CASCADE"), nullable=False
    )
    weekly_pieces: Mapped[float] = mapped_column(Numeric(10, 2), nullable=False)
    weeks_to_clear: Mapped[float | None] = mapped_column(Numeric(8, 1), default=None)
    at_risk: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    reason: Mapped[str] = mapped_column(String(300), nullable=False)
    computed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ProductionWarning(UUIDPrimaryKey, TimestampMixin, Base):
    """A brand holds more of a category than the market is buying."""

    __tablename__ = "production_warnings"

    brand_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("brands.id", ondelete="CASCADE"), nullable=False
    )
    category_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("categories.id", ondelete="CASCADE"), nullable=False
    )
    live_pieces: Mapped[int] = mapped_column(Integer, nullable=False)
    weekly_demand: Mapped[float] = mapped_column(Numeric(10, 2), nullable=False)
    weeks_of_demand: Mapped[float | None] = mapped_column(Numeric(8, 1), default=None)
    message: Mapped[str] = mapped_column(String(400), nullable=False)
    computed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
