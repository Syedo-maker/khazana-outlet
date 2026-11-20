"""Committee pools: several resellers in one city buying one lot together.

Pakistani shopkeepers already pool money in a "committee". This is the same
idea for stock: a lot too large for one shop is bought by three or four, each
taking the sizes and colours they need.

Members never see each other's names or numbers. A pool shows how many places
are taken and what is still uncovered, nothing about who took them.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, Index, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base, TimestampMixin, UUIDPrimaryKey
from .enums import PaymentMethod, PoolStatus


class Pool(UUIDPrimaryKey, TimestampMixin, Base):
    __tablename__ = "pools"

    lot_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("lots.id", ondelete="CASCADE"), nullable=False
    )
    organiser_user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    city: Mapped[str] = mapped_column(String(80), nullable=False)
    status: Mapped[PoolStatus] = mapped_column(nullable=False, default=PoolStatus.OPEN)
    closes_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ordered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)

    members: Mapped[list[PoolMember]] = relationship(
        back_populates="pool", order_by="PoolMember.created_at", cascade="all, delete-orphan"
    )

    __table_args__ = (Index("ix_pools_city_status", "city", "status"),)


class PoolMember(UUIDPrimaryKey, TimestampMixin, Base):
    __tablename__ = "pool_members"

    pool_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("pools.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    # {"lines": [{"size": "M", "color": "black", "pieces": 20}, ...]}
    requested: Mapped[dict[str, Any]] = mapped_column(nullable=False)
    allocated: Mapped[dict[str, Any] | None] = mapped_column(default=None)
    delivery_address: Mapped[str] = mapped_column(String(500), nullable=False)
    delivery_phone: Mapped[str] = mapped_column(String(11), nullable=False)
    payment_method: Mapped[PaymentMethod] = mapped_column(nullable=False)
    order_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("orders.id", ondelete="SET NULL"), default=None
    )

    pool: Mapped[Pool] = relationship(back_populates="members")

    __table_args__ = (UniqueConstraint("pool_id", "user_id", name="one_place_per_member"),)
