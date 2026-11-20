"""Reference data the intelligence features read.

Each row here is a number a person set and can change, never one a model
produced. The features that read them compute; they do not invent.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import CheckConstraint, ForeignKey, Integer, Numeric, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, TimestampMixin, UUIDPrimaryKey


class ResaleBenchmark(UUIDPrimaryKey, TimestampMixin, Base):
    """What resellers typically get for stock, as a share of the retail price.

    Matched most specific first: category and city, then category, then city,
    then the row with neither, which always exists. The profit helper shows
    which row it used, so a buyer can see the assumption behind an estimate.
    """

    __tablename__ = "resale_benchmarks"

    category_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("categories.id", ondelete="CASCADE"), default=None
    )
    city: Mapped[str | None] = mapped_column(String(80), default=None)
    low_percent: Mapped[float] = mapped_column(Numeric(5, 2), nullable=False)
    typical_percent: Mapped[float] = mapped_column(Numeric(5, 2), nullable=False)
    high_percent: Mapped[float] = mapped_column(Numeric(5, 2), nullable=False)
    note: Mapped[str] = mapped_column(String(300), nullable=False, default="")

    __table_args__ = (
        UniqueConstraint("category_id", "city", name="one_benchmark_per_category_city"),
        CheckConstraint(
            "low_percent > 0 AND low_percent <= typical_percent "
            "AND typical_percent <= high_percent AND high_percent <= 100",
            name="resale_percents_ordered",
        ),
    )


class ResellKit(UUIDPrimaryKey, TimestampMixin, Base):
    """The marketing kit generated for one purchased order.

    Kept so that opening the kit again costs nothing. Regenerating replaces it,
    for example after the buyer changes their selling price.
    """

    __tablename__ = "resell_kits"

    order_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("orders.id", ondelete="CASCADE"), nullable=False, unique=True
    )
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    selling_price_pkr: Mapped[int] = mapped_column(Integer, nullable=False)
    copy: Mapped[dict[str, Any]] = mapped_column(nullable=False)
