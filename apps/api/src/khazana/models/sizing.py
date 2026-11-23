"""Size charts, for translating one brand's sizes into a common standard.

A brand's M is not another brand's M, and a buyer who guesses wrong sends the
stock back. Each brand enters its own chart in centimetres; the platform holds
a standard chart; code maps each brand size to the nearest standard size by
measurement. Buyers see the standard size and the measurements, never another
brand's chart.
"""

from __future__ import annotations

from sqlalchemy import ForeignKey, Numeric, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, TimestampMixin, UUIDPrimaryKey


class _Measured:
    chest_min_cm: Mapped[float | None] = mapped_column(Numeric(5, 1), default=None)
    chest_max_cm: Mapped[float | None] = mapped_column(Numeric(5, 1), default=None)
    waist_min_cm: Mapped[float | None] = mapped_column(Numeric(5, 1), default=None)
    waist_max_cm: Mapped[float | None] = mapped_column(Numeric(5, 1), default=None)
    hip_min_cm: Mapped[float | None] = mapped_column(Numeric(5, 1), default=None)
    hip_max_cm: Mapped[float | None] = mapped_column(Numeric(5, 1), default=None)


class StandardSize(_Measured, UUIDPrimaryKey, TimestampMixin, Base):
    """The platform's reference sizes, per audience. Administrator maintained."""

    __tablename__ = "standard_sizes"

    audience: Mapped[str] = mapped_column(String(16), nullable=False)
    label: Mapped[str] = mapped_column(String(16), nullable=False)

    __table_args__ = (UniqueConstraint("audience", "label", name="one_standard_label"),)


class SizeChartRow(_Measured, UUIDPrimaryKey, TimestampMixin, Base):
    """One size in one brand's own chart."""

    __tablename__ = "size_chart_rows"

    brand_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("brands.id", ondelete="CASCADE"), nullable=False
    )
    audience: Mapped[str] = mapped_column(String(16), nullable=False)
    label: Mapped[str] = mapped_column(String(32), nullable=False)

    __table_args__ = (
        UniqueConstraint("brand_id", "audience", "label", name="one_brand_size_label"),
    )
