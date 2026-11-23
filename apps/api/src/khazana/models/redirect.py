"""The upcycle and donation route, and the factors the impact report uses.

Stock that will not sell can still be used: by tailors and artisans who cut
it into something new, by NGOs who give it away, by recyclers. Partners are
kept by administrators and have no accounts; an administrator coordinates
each handover and records what happened.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, TimestampMixin, UUIDPrimaryKey
from .enums import RedirectStatus


class Partner(UUIDPrimaryKey, TimestampMixin, Base):
    __tablename__ = "partners"

    name: Mapped[str] = mapped_column(String(160), nullable=False)
    # tailor, artisan, ngo or recycler
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    city: Mapped[str] = mapped_column(String(80), nullable=False)
    # {"words": ["kurta", "lawn"]}, matched against category names; empty takes anything.
    categories: Mapped[dict[str, Any]] = mapped_column(nullable=False)
    # {"grades": ["B", "C"]}
    grades: Mapped[dict[str, Any]] = mapped_column(nullable=False)
    min_pieces: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    max_pieces: Mapped[int | None] = mapped_column(Integer, default=None)
    # Seen by administrators only. Brands see the name, kind and city.
    contact_name: Mapped[str] = mapped_column(String(120), nullable=False, default="")
    contact_phone: Mapped[str] = mapped_column(String(20), nullable=False, default="")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class Redirection(UUIDPrimaryKey, TimestampMixin, Base):
    """One lot offered to one partner, and what became of it."""

    __tablename__ = "redirections"

    lot_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("lots.id", ondelete="CASCADE"), nullable=False
    )
    brand_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("brands.id", ondelete="CASCADE"), nullable=False
    )
    partner_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("partners.id", ondelete="RESTRICT"), nullable=False
    )
    # donation or upcycle_sale
    route: Mapped[str] = mapped_column(String(16), nullable=False)
    pieces: Mapped[int] = mapped_column(Integer, nullable=False)
    price_pkr: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    status: Mapped[RedirectStatus] = mapped_column(nullable=False, default=RedirectStatus.PROPOSED)
    note: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    collected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)


class ImpactFactor(UUIDPrimaryKey, TimestampMixin, Base):
    """Weight, water and carbon per piece for a kind of product.

    Published averages, matched by keyword against category names, with a
    ``*`` row for everything else. An administrator replaces them with better
    data; the impact report shows which factor it used.
    """

    __tablename__ = "impact_factors"

    keyword: Mapped[str] = mapped_column(String(40), nullable=False, unique=True)
    kg_per_piece: Mapped[float] = mapped_column(Numeric(6, 3), nullable=False)
    water_litres_per_kg: Mapped[float] = mapped_column(Numeric(10, 1), nullable=False)
    co2_kg_per_kg: Mapped[float] = mapped_column(Numeric(6, 2), nullable=False)
    source: Mapped[str] = mapped_column(String(300), nullable=False, default="")
