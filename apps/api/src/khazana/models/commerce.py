"""Orders, payments, brand payouts, shipments and disputes.

The money path is deliberately dull. Every amount is an integer number of
rupees, never a float, because a float rounding error in a payout is a
conversation with a brand you do not want to have. Paisa are not used: the
Pakistani market prices these goods in whole rupees.

Commission is copied onto the order at the time it is placed. Reading it live
from the brand policy would mean that changing a rate silently rewrites the
history of what was owed on past orders.
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base, TimestampMixin, UUIDPrimaryKey
from .enums import (
    DisputeStatus,
    OrderStatus,
    PaymentMethod,
    PaymentStatus,
    PayoutStatus,
    ShipmentStatus,
)

if TYPE_CHECKING:
    pass


class Order(UUIDPrimaryKey, TimestampMixin, Base):
    """One purchase of one lot, whole or part."""

    __tablename__ = "orders"
    __mapper_args__ = {"version_id_col": None}  # replaced below

    order_code: Mapped[str] = mapped_column(String(24), unique=True, nullable=False)
    lot_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("lots.id", ondelete="RESTRICT"), nullable=False
    )
    # Denormalised so a brand's orders are one indexed lookup, and so the
    # tenancy policy does not need a join.
    brand_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("brands.id", ondelete="RESTRICT"), nullable=False
    )
    buyer_user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )

    pieces: Mapped[int] = mapped_column(Integer, nullable=False)
    unit_price_pkr: Mapped[int] = mapped_column(Integer, nullable=False)
    subtotal_pkr: Mapped[int] = mapped_column(Integer, nullable=False)
    shipping_pkr: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    total_pkr: Mapped[int] = mapped_column(Integer, nullable=False)

    # Snapshotted from BrandPolicy when the order is created. See the module
    # docstring for why this is not read live.
    commission_percent: Mapped[float] = mapped_column(Numeric(5, 2), nullable=False)
    commission_pkr: Mapped[int] = mapped_column(Integer, nullable=False)
    brand_payout_pkr: Mapped[int] = mapped_column(Integer, nullable=False)

    status: Mapped[OrderStatus] = mapped_column(
        String(20), nullable=False, default=OrderStatus.CREATED
    )
    delivery_city: Mapped[str] = mapped_column(String(80), nullable=False)
    delivery_address: Mapped[str] = mapped_column(String(500), nullable=False)
    delivery_phone: Mapped[str] = mapped_column(String(11), nullable=False)

    # The window in which a buyer may report that goods do not match the
    # manifest. Money is not released to the brand before it closes.
    dispute_window_ends_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), default=None
    )
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    cancellation_reason: Mapped[str | None] = mapped_column(String(500), default=None)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    lines: Mapped[list[OrderLine]] = relationship(
        back_populates="order", cascade="all, delete-orphan"
    )
    payments: Mapped[list[Payment]] = relationship(back_populates="order")
    shipments: Mapped[list[Shipment]] = relationship(back_populates="order")
    disputes: Mapped[list[Dispute]] = relationship(back_populates="order")
    payout: Mapped[Payout | None] = relationship(back_populates="order", uselist=False)

    __table_args__ = (
        CheckConstraint("pieces > 0", name="order_pieces_positive"),
        CheckConstraint("unit_price_pkr > 0", name="order_unit_price_positive"),
        CheckConstraint("shipping_pkr >= 0", name="order_shipping_non_negative"),
        CheckConstraint("commission_pkr >= 0", name="order_commission_non_negative"),
        # The arithmetic is constrained, not merely computed in Python, so no
        # code path can persist an order whose totals do not add up.
        CheckConstraint("subtotal_pkr = pieces * unit_price_pkr", name="order_subtotal_consistent"),
        CheckConstraint("total_pkr = subtotal_pkr + shipping_pkr", name="order_total_consistent"),
        CheckConstraint(
            "brand_payout_pkr = subtotal_pkr - commission_pkr", name="order_payout_consistent"
        ),
        Index("ix_orders_brand_status", "brand_id", "status"),
        Index("ix_orders_buyer_created", "buyer_user_id", "created_at"),
        Index("ix_orders_lot", "lot_id"),
    )


Order.__mapper_args__ = {"version_id_col": Order.__table__.c.version}


class OrderLine(UUIDPrimaryKey, TimestampMixin, Base):
    """Size and colour breakdown of what was actually bought.

    For a whole lot order this mirrors the manifest. For a part lot order it
    is the subset the buyer chose, which is what the warehouse picks against.
    """

    __tablename__ = "order_lines"

    order_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("orders.id", ondelete="CASCADE"), nullable=False
    )
    brand_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("brands.id", ondelete="RESTRICT"), nullable=False
    )
    size: Mapped[str] = mapped_column(String(32), nullable=False)
    color: Mapped[str] = mapped_column(String(48), nullable=False)
    pieces: Mapped[int] = mapped_column(Integer, nullable=False)
    unit_price_pkr: Mapped[int] = mapped_column(Integer, nullable=False)

    order: Mapped[Order] = relationship(back_populates="lines")

    __table_args__ = (
        UniqueConstraint("order_id", "size", "color", name="one_order_line_per_size_colour"),
        CheckConstraint("pieces > 0", name="order_line_pieces_positive"),
    )


class Payment(UUIDPrimaryKey, TimestampMixin, Base):
    """Money in from a buyer, and the escrow state machine.

    ``HELD`` is the state that makes the platform trustworthy to both sides:
    the buyer has paid, the brand has not been paid, and neither can be
    cheated by the other.
    """

    __tablename__ = "payments"

    order_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("orders.id", ondelete="RESTRICT"), nullable=False
    )
    method: Mapped[PaymentMethod] = mapped_column(String(20), nullable=False)
    status: Mapped[PaymentStatus] = mapped_column(
        String(16), nullable=False, default=PaymentStatus.PENDING
    )
    amount_pkr: Mapped[int] = mapped_column(Integer, nullable=False)
    provider: Mapped[str | None] = mapped_column(String(40), default=None)
    provider_reference: Mapped[str | None] = mapped_column(String(120), default=None)
    held_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    released_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    refunded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    failure_reason: Mapped[str | None] = mapped_column(String(500), default=None)
    # Raw provider callback, kept verbatim for reconciliation and disputes.
    provider_payload: Mapped[dict[str, object] | None] = mapped_column(default=None)

    order: Mapped[Order] = relationship(back_populates="payments")

    __table_args__ = (
        CheckConstraint("amount_pkr > 0", name="payment_amount_positive"),
        UniqueConstraint(
            "provider", "provider_reference", name="one_payment_per_provider_reference"
        ),
        Index("ix_payments_order_status", "order_id", "status"),
    )


class Payout(UUIDPrimaryKey, TimestampMixin, Base):
    """Money out to a brand, one row per order."""

    __tablename__ = "payouts"

    order_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("orders.id", ondelete="RESTRICT"), unique=True, nullable=False
    )
    brand_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("brands.id", ondelete="RESTRICT"), nullable=False
    )
    amount_pkr: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[PayoutStatus] = mapped_column(
        String(16), nullable=False, default=PayoutStatus.PENDING
    )
    scheduled_for: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    reference: Mapped[str | None] = mapped_column(String(120), default=None)
    note: Mapped[str | None] = mapped_column(String(500), default=None)
    # Who pressed the button. Payouts are never fully automatic in the MVP.
    approved_by_user_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="SET NULL"), default=None
    )

    order: Mapped[Order] = relationship(back_populates="payout")

    __table_args__ = (
        CheckConstraint("amount_pkr >= 0", name="payout_amount_non_negative"),
        Index("ix_payouts_brand_status", "brand_id", "status"),
    )


class Shipment(UUIDPrimaryKey, TimestampMixin, Base):
    """A courier consignment. One order may ship in more than one."""

    __tablename__ = "shipments"

    order_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("orders.id", ondelete="CASCADE"), nullable=False
    )
    brand_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("brands.id", ondelete="RESTRICT"), nullable=False
    )
    courier: Mapped[str] = mapped_column(String(40), nullable=False)
    tracking_number: Mapped[str | None] = mapped_column(String(80), default=None)
    status: Mapped[ShipmentStatus] = mapped_column(
        String(20), nullable=False, default=ShipmentStatus.PENDING_PICKUP
    )
    cost_pkr: Mapped[int | None] = mapped_column(Integer, default=None)
    cartons: Mapped[int | None] = mapped_column(Integer, default=None)
    weight_kg: Mapped[float | None] = mapped_column(Numeric(8, 2), default=None)
    label_key: Mapped[str | None] = mapped_column(String(500), default=None)
    picked_up_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)

    order: Mapped[Order] = relationship(back_populates="shipments")

    __table_args__ = (
        UniqueConstraint("courier", "tracking_number", name="one_shipment_per_tracking_number"),
        Index("ix_shipments_order", "order_id"),
    )


class Dispute(UUIDPrimaryKey, TimestampMixin, Base):
    """A buyer says the goods do not match the manifest.

    The resolution fields are filled by an admin, never by a model. Risk
    scoring may rank the queue, it may not decide the outcome.
    """

    __tablename__ = "disputes"

    order_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("orders.id", ondelete="CASCADE"), nullable=False
    )
    brand_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("brands.id", ondelete="RESTRICT"), nullable=False
    )
    raised_by_user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    reason: Mapped[str] = mapped_column(String(120), nullable=False)
    detail: Mapped[str | None] = mapped_column(Text, default=None)
    evidence_keys: Mapped[dict[str, object] | None] = mapped_column(default=None)
    status: Mapped[DisputeStatus] = mapped_column(
        String(20), nullable=False, default=DisputeStatus.OPEN
    )
    resolution: Mapped[str | None] = mapped_column(Text, default=None)
    refund_pkr: Mapped[int | None] = mapped_column(Integer, default=None)
    resolved_by_user_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="SET NULL"), default=None
    )
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)

    order: Mapped[Order] = relationship(back_populates="disputes")

    __table_args__ = (
        CheckConstraint("refund_pkr is null or refund_pkr >= 0", name="refund_non_negative"),
        Index("ix_disputes_status_created", "status", "created_at"),
    )
