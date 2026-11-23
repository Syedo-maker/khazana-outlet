"""Negotiations with the bargaining bot, under ADR 0001.

A negotiation is one buyer bargaining over one whole lot. Every price the bot
offers is chosen by the model inside a range code computed, clamped again by
code, and written to the append only audit trail. The floor is stored here so
an agreement can be checked against the floor that applied when it was made,
and it is never sent to the buyer or to the model.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base, TimestampMixin, UUIDPrimaryKey
from .enums import ChatRole, NegotiationStatus


class Negotiation(UUIDPrimaryKey, TimestampMixin, Base):
    __tablename__ = "negotiations"

    lot_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("lots.id", ondelete="CASCADE"), nullable=False
    )
    brand_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("brands.id", ondelete="CASCADE"), nullable=False
    )
    buyer_user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    status: Mapped[NegotiationStatus] = mapped_column(
        nullable=False, default=NegotiationStatus.OPEN
    )
    pieces: Mapped[int] = mapped_column(Integer, nullable=False)
    list_price_pkr: Mapped[int] = mapped_column(Integer, nullable=False)
    floor_price_pkr: Mapped[int] = mapped_column(Integer, nullable=False)
    step_pkr: Mapped[int] = mapped_column(Integer, nullable=False)
    asking_price_pkr: Mapped[int] = mapped_column(Integer, nullable=False)
    rounds: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    agreed_price_pkr: Mapped[int | None] = mapped_column(Integer, default=None)
    agreed_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    order_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("orders.id", ondelete="SET NULL"), default=None
    )

    messages: Mapped[list[NegotiationMessage]] = relationship(
        back_populates="negotiation",
        order_by="NegotiationMessage.created_at",
        cascade="all, delete-orphan",
    )


class NegotiationMessage(UUIDPrimaryKey, TimestampMixin, Base):
    __tablename__ = "negotiation_messages"

    negotiation_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("negotiations.id", ondelete="CASCADE"), nullable=False
    )
    brand_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("brands.id", ondelete="CASCADE"), nullable=False
    )
    role: Mapped[ChatRole] = mapped_column(nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    offer_pkr: Mapped[int | None] = mapped_column(Integer, default=None)
    # What the model proposed, and whether the clamp had to change it. Kept
    # so the eval's claim that the clamp rarely acts can be checked in
    # production too.
    proposed_pkr: Mapped[int | None] = mapped_column(Integer, default=None)
    clamped: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    negotiation: Mapped[Negotiation] = relationship(back_populates="messages")
