"""Cart, ordering and the order lifecycle.

Three promises are kept here:

1. **Stock is sold once.** The lot row is locked while pieces are reserved, and
   a database constraint keeps the reservation inside the lot.
2. **The money adds up.** Amounts are whole rupees, commission is copied onto
   the order when it is placed, and whoever buys the last of a lot pays exactly
   what remains of the listed price.
3. **Every status change is recorded.** All of them go through `_move`, which
   checks the transition table and writes the event both sides can read.

The region lock is checked against the delivery city, because the place the
stock ends up is what a brand is protecting.
"""

from __future__ import annotations

import re
import secrets
from collections import Counter
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from math import ceil
from types import ModuleType
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.orm import Session, selectinload

from ..core.errors import Conflict, Forbidden, NotFound, ValidationFailed
from ..models import (
    Brand,
    BrandPolicy,
    CartItem,
    Dispute,
    Lot,
    ManifestLine,
    Order,
    OrderEvent,
    OrderLine,
    OrderReturn,
    User,
)
from ..models.base import utcnow
from ..models.enums import (
    DisputeStatus,
    LotStatus,
    OrderStatus,
    PaymentMethod,
    UserRole,
    VerificationStatus,
)
from . import approval_service, audit_service, catalog_service, logistics_service

ORDER_TRANSITIONS: dict[OrderStatus, frozenset[OrderStatus]] = {
    OrderStatus.CREATED: frozenset(
        {OrderStatus.AWAITING_PAYMENT, OrderStatus.PREPARING, OrderStatus.CANCELLED}
    ),
    OrderStatus.AWAITING_PAYMENT: frozenset({OrderStatus.PAID, OrderStatus.CANCELLED}),
    OrderStatus.PAID: frozenset({OrderStatus.PREPARING, OrderStatus.REFUNDED}),
    OrderStatus.PREPARING: frozenset(
        {OrderStatus.SHIPPED, OrderStatus.CANCELLED, OrderStatus.REFUNDED}
    ),
    OrderStatus.SHIPPED: frozenset({OrderStatus.DELIVERED, OrderStatus.REFUNDED}),
    OrderStatus.DELIVERED: frozenset({OrderStatus.CONFIRMED, OrderStatus.DISPUTED}),
    OrderStatus.DISPUTED: frozenset({OrderStatus.CONFIRMED, OrderStatus.REFUNDED}),
    OrderStatus.CONFIRMED: frozenset(),
    OrderStatus.CANCELLED: frozenset(),
    OrderStatus.REFUNDED: frozenset(),
}

RELEASES_STOCK = frozenset({OrderStatus.CANCELLED, OrderStatus.REFUNDED})
FINISHED = frozenset({OrderStatus.CONFIRMED, OrderStatus.CANCELLED, OrderStatus.REFUNDED})
BUYER_CANCELLABLE = frozenset(
    {OrderStatus.CREATED, OrderStatus.AWAITING_PAYMENT, OrderStatus.PREPARING}
)

# These run in sandbox today. Card is in the enum for later and is not offered.
OFFERED_METHODS = frozenset(
    {
        PaymentMethod.BANK_TRANSFER,
        PaymentMethod.JAZZCASH,
        PaymentMethod.EASYPAISA,
        PaymentMethod.COD,
    }
)

_PHONE = re.compile(r"^03\d{9}$")
_CODE_ALPHABET = "ABCDEFGHJKMNPQRTUVWXYZ2346789"


@dataclass(frozen=True, slots=True)
class LineChoice:
    size: str
    color: str
    pieces: int


@dataclass(frozen=True, slots=True)
class Purchase:
    lot_id: str
    whole_lot: bool = True
    lines: tuple[LineChoice, ...] = ()


@dataclass(frozen=True, slots=True)
class Delivery:
    city: str
    address: str
    phone: str


@dataclass(slots=True)
class Pricing:
    pieces: int
    unit_price_pkr: int
    rounding_adjustment_pkr: int
    subtotal_pkr: int
    shipping_pkr: int
    total_pkr: int
    commission_percent: Decimal
    commission_pkr: int
    brand_payout_pkr: int
    lines: list[LineChoice] = field(default_factory=list)


# ---------------------------------------------------------------- availability


def active_order_lines(db: Session, lot_id: str) -> Counter[tuple[str, str]]:
    rows = db.execute(
        select(OrderLine.size, OrderLine.color, OrderLine.pieces)
        .join(Order, Order.id == OrderLine.order_id)
        .where(Order.lot_id == lot_id, Order.status.not_in(RELEASES_STOCK))
    ).all()
    taken: Counter[tuple[str, str]] = Counter()
    for size, color, pieces in rows:
        taken[(size, color)] += pieces
    return taken


def available_lines(db: Session, lot: Lot) -> list[LineChoice]:
    """What is left of each size and colour."""
    taken = active_order_lines(db, lot.id)
    remaining = [
        LineChoice(
            size=line.size,
            color=line.color,
            pieces=line.pieces - taken[(line.size, line.color)],
        )
        for line in sorted(lot.manifest_lines, key=lambda item: (item.size, item.color))
    ]
    return [line for line in remaining if line.pieces > 0]


def _money_already_committed(db: Session, lot_id: str) -> int:
    rows = db.scalars(
        select(Order.subtotal_pkr).where(
            Order.lot_id == lot_id, Order.status.not_in(RELEASES_STOCK)
        )
    ).all()
    return sum(rows)


def _chosen_lines(
    db: Session, lot: Lot, purchase: Purchase, policy: BrandPolicy, *, pooled: bool = False
) -> list[LineChoice]:
    remaining = available_lines(db, lot)
    if purchase.whole_lot:
        if not remaining:
            raise Conflict("This lot has sold out.")
        return remaining

    if pooled:
        if not policy.allow_pooled_orders:
            raise ValidationFailed("This brand does not allow pooled orders.")
    elif not policy.allow_part_lot_orders:
        raise ValidationFailed("This brand sells this lot only as a whole.")
    if not purchase.lines:
        raise ValidationFailed("Choose at least one size and colour.")

    stock = {(line.size, line.color): line.pieces for line in remaining}
    seen: set[tuple[str, str]] = set()
    for line in purchase.lines:
        key = (line.size, line.color)
        if key in seen:
            raise ValidationFailed(f"{line.size} {line.color} is listed twice.")
        seen.add(key)
        if line.pieces <= 0:
            raise ValidationFailed("Each size and colour needs at least 1 piece.")
        if line.pieces > stock.get(key, 0):
            raise Conflict(
                f"Only {stock.get(key, 0)} pieces of {line.size} {line.color} are available."
            )
    return list(purchase.lines)


def price_purchase(
    db: Session,
    *,
    lot: Lot,
    purchase: Purchase,
    destination_city: str,
    pooled: bool = False,
) -> Pricing:
    """Price one purchase exactly as checkout will.

    ``pooled`` is for one member's share of a committee pool. The per order
    minimums are then the pool's to meet as a whole, and the pool service
    checks them across all members before any order exists.
    """
    policy = _policy(db, lot.brand_id)
    lines = _chosen_lines(db, lot, purchase, policy, pooled=pooled)
    pieces = sum(line.pieces for line in lines)
    available = lot.available_pieces

    if pieces > available:
        raise Conflict(f"Only {available} pieces of this lot are available.")
    takes_the_rest = pieces == available
    if pieces < lot.min_order_pieces and not takes_the_rest and not pooled:
        raise ValidationFailed(f"The minimum order for this lot is {lot.min_order_pieces} pieces.")

    unit_price = ceil(lot.lot_price_pkr / lot.total_pieces)
    subtotal = pieces * unit_price
    if takes_the_rest:
        # The orders on one lot always add up to its listed price.
        subtotal = max(pieces, lot.lot_price_pkr - _money_already_committed(db, lot.id))
    elif subtotal < policy.min_lot_value_pkr and not pooled:
        raise ValidationFailed(
            f"The minimum order value for this brand is {policy.min_lot_value_pkr:,} PKR."
        )

    shipping = logistics_service.quote(
        db, lot=lot, pieces=pieces, destination_city=destination_city
    ).cost_pkr
    percent = Decimal(str(policy.commission_percent))
    commission = int(
        (Decimal(subtotal) * percent / Decimal(100)).quantize(Decimal(1), rounding=ROUND_HALF_UP)
    )
    return Pricing(
        pieces=pieces,
        unit_price_pkr=unit_price,
        rounding_adjustment_pkr=subtotal - pieces * unit_price,
        subtotal_pkr=subtotal,
        shipping_pkr=shipping,
        total_pkr=subtotal + shipping,
        commission_percent=percent,
        commission_pkr=commission,
        brand_payout_pkr=subtotal - commission,
        lines=lines,
    )


# -------------------------------------------------------------------- ordering


def require_buyer(db: Session, user: User) -> None:
    if user.role != UserRole.RESELLER:
        raise Forbidden("Orders are placed from a reseller account.")
    profile = user.reseller_profile
    if profile is None or VerificationStatus(profile.status) != VerificationStatus.VERIFIED:
        raise Forbidden("Your business has to be verified before you can order.")


def buyable_lot(db: Session, *, lot_id: str, city: str, lock: bool = False) -> Lot:
    """A lot this verified buyer may have delivered to this city."""
    statement = (
        select(Lot)
        .where(
            Lot.id == lot_id,
            approval_service.visibility_filter(
                role=UserRole.RESELLER, reseller_is_verified=True, city=city
            ),
        )
        .options(selectinload(Lot.manifest_lines), selectinload(Lot.photos))
        .execution_options(populate_existing=True)
    )
    if lock:
        statement = statement.with_for_update(of=Lot)
    lot = db.scalars(statement).first()
    if lot is None:
        raise NotFound("That lot is not available for delivery to this city.")

    brand = db.get(Brand, lot.brand_id)
    if brand is None or VerificationStatus(brand.status) != VerificationStatus.VERIFIED:
        raise Conflict("This brand is not able to take orders at the moment.")
    return lot


def place_orders(
    db: Session,
    *,
    buyer: User,
    purchases: list[Purchase],
    delivery: Delivery,
    method: PaymentMethod,
    ip: str | None = None,
) -> list[Order]:
    """Create one order per lot, all of them or none.

    Lots are locked in identifier order, so two buyers with overlapping carts
    cannot deadlock each other.
    """
    require_buyer(db, buyer)
    cleaned = _clean_delivery(delivery)
    if method not in OFFERED_METHODS:
        raise ValidationFailed("That payment method is not available.")
    if not purchases:
        raise ValidationFailed("There is nothing to order.")
    if len({purchase.lot_id for purchase in purchases}) != len(purchases):
        raise ValidationFailed("Each lot can appear only once in an order.")

    orders: list[Order] = []
    for purchase in sorted(purchases, key=lambda item: item.lot_id):
        lot = buyable_lot(db, lot_id=purchase.lot_id, city=cleaned.city, lock=True)
        policy = _policy(db, lot.brand_id)
        if method == PaymentMethod.COD and not policy.allow_cod:
            raise ValidationFailed(f"Cash on delivery is not available for {lot.lot_code}.")

        pricing = price_purchase(db, lot=lot, purchase=purchase, destination_city=cleaned.city)
        orders.append(
            create_order(
                db, buyer=buyer, lot=lot, pricing=pricing, delivery=cleaned, method=method, ip=ip
            )
        )
        db.execute(delete(CartItem).where(CartItem.user_id == buyer.id, CartItem.lot_id == lot.id))
    return orders


def create_order(
    db: Session,
    *,
    buyer: User,
    lot: Lot,
    pricing: Pricing,
    delivery: Delivery,
    method: PaymentMethod,
    ip: str | None = None,
) -> Order:
    """Write one priced order, reserve its pieces and move it to its first state.

    The caller has locked the lot and priced the purchase. Checkout and pooled
    orders both come through here, so an order is the same thing either way.
    """
    order = Order(
        order_code=_new_code(db),
        lot_id=lot.id,
        brand_id=lot.brand_id,
        buyer_user_id=buyer.id,
        pieces=pricing.pieces,
        unit_price_pkr=pricing.unit_price_pkr,
        rounding_adjustment_pkr=pricing.rounding_adjustment_pkr,
        subtotal_pkr=pricing.subtotal_pkr,
        shipping_pkr=pricing.shipping_pkr,
        total_pkr=pricing.total_pkr,
        commission_percent=pricing.commission_percent,
        commission_pkr=pricing.commission_pkr,
        brand_payout_pkr=pricing.brand_payout_pkr,
        status=OrderStatus.CREATED,
        payment_method=method,
        delivery_city=delivery.city,
        delivery_address=delivery.address,
        delivery_phone=delivery.phone,
    )
    order.lines = [
        OrderLine(
            brand_id=lot.brand_id,
            size=line.size,
            color=line.color,
            pieces=line.pieces,
            unit_price_pkr=pricing.unit_price_pkr,
        )
        for line in pricing.lines
    ]
    db.add(order)
    lot.reserved_pieces += pricing.pieces
    db.flush()

    _record_event(db, order, None, OrderStatus.CREATED, actor=buyer, note=None)
    next_status = (
        OrderStatus.PREPARING if method == PaymentMethod.COD else OrderStatus.AWAITING_PAYMENT
    )
    _move(db, order, next_status, actor=buyer, ip=ip)
    return order


def get_order(db: Session, order_id: str) -> Order:
    order = db.scalars(
        select(Order)
        .where(Order.id == order_id)
        .options(
            selectinload(Order.lines),
            selectinload(Order.events),
            selectinload(Order.returns),
            selectinload(Order.disputes),
            selectinload(Order.payments),
            selectinload(Order.shipments),
        )
    ).first()
    if order is None:
        raise NotFound("That order does not exist.")
    return order


def list_orders(
    db: Session,
    *,
    buyer_user_id: str | None = None,
    brand_ids: list[str] | None = None,
    status: OrderStatus | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[Order]:
    statement = select(Order).options(selectinload(Order.lines))
    if buyer_user_id is not None:
        statement = statement.where(Order.buyer_user_id == buyer_user_id)
    if brand_ids is not None:
        statement = statement.where(Order.brand_id.in_(brand_ids))
    if status is not None:
        statement = statement.where(Order.status == status)
    return list(
        db.scalars(statement.order_by(Order.created_at.desc()).limit(limit).offset(offset)).all()
    )


# ------------------------------------------------------------------- lifecycle


def mark_paid(db: Session, order: Order, *, note: str | None = None) -> Order:
    return _move(db, order, OrderStatus.PAID, actor=None, note=note)


def start_preparing(db: Session, order: Order, *, actor: User, ip: str | None = None) -> Order:
    if OrderStatus(order.status) == OrderStatus.PREPARING:
        return order
    return _move(db, order, OrderStatus.PREPARING, actor=actor, ip=ip)


def mark_shipped(db: Session, order: Order, *, note: str | None = None) -> Order:
    return _move(db, order, OrderStatus.SHIPPED, actor=None, note=note)


def mark_delivered(db: Session, order: Order, *, note: str | None = None) -> Order:
    """Delivery starts the window in which the buyer can report a problem."""
    now = utcnow()
    policy = _policy(db, order.brand_id)
    order.delivered_at = now
    order.dispute_window_ends_at = now + timedelta(days=policy.dispute_window_days)
    _move(db, order, OrderStatus.DELIVERED, actor=None, note=note)
    _payments().record_cod_collection(db, order)
    return order


def cancel(
    db: Session,
    order: Order,
    *,
    actor: User,
    reason: str,
    ip: str | None = None,
) -> Order:
    """Cancel an order that has not been paid for or shipped.

    Paid orders are refunded rather than cancelled, because money has moved.
    """
    if OrderStatus(order.status) not in BUYER_CANCELLABLE:
        raise Conflict(f"An order that is {order.status} cannot be cancelled.")
    cleaned = reason.strip()
    if len(cleaned) < 3:
        raise ValidationFailed("Say why this order is being cancelled.")
    order.cancelled_at = utcnow()
    order.cancellation_reason = cleaned[:500]
    _move(db, order, OrderStatus.CANCELLED, actor=actor, note=cleaned, ip=ip)
    _payments().on_order_cancelled(db, order)
    return order


def confirm_delivery(db: Session, order: Order, *, actor: User, ip: str | None = None) -> Order:
    if OrderStatus(order.status) != OrderStatus.DELIVERED:
        raise Conflict("Only a delivered order can be confirmed.")
    return _complete(db, order, actor=actor, note="Confirmed by the buyer.", ip=ip)


def close_expired_windows(db: Session, *, now: datetime | None = None) -> int:
    """Confirm delivered orders whose dispute window has passed."""
    moment = now or utcnow()
    orders = db.scalars(
        select(Order).where(
            Order.status == OrderStatus.DELIVERED,
            Order.dispute_window_ends_at.is_not(None),
            Order.dispute_window_ends_at <= moment,
        )
    ).all()
    for order in orders:
        _complete(db, order, actor=None, note="The dispute window closed with no report.")
    return len(orders)


def open_dispute(
    db: Session,
    order: Order,
    *,
    actor: User,
    reason: str,
    detail: str | None,
    ip: str | None = None,
) -> Dispute:
    if OrderStatus(order.status) != OrderStatus.DELIVERED:
        raise Conflict("A problem can be reported once the order has been delivered.")
    ends = _aware(order.dispute_window_ends_at)
    if ends is None or ends <= utcnow():
        raise Conflict("The time to report a problem with this order has passed.")

    dispute = Dispute(
        order_id=order.id,
        brand_id=order.brand_id,
        raised_by_user_id=actor.id,
        reason=reason.strip()[:120],
        detail=(detail or "").strip() or None,
    )
    order.disputes.append(dispute)
    _move(db, order, OrderStatus.DISPUTED, actor=actor, note=dispute.reason, ip=ip)
    return dispute


def record_return(
    db: Session,
    order: Order,
    *,
    actor: User,
    pieces: int,
    reason: str,
    ip: str | None = None,
) -> OrderReturn:
    if OrderStatus(order.status) not in {
        OrderStatus.DELIVERED,
        OrderStatus.DISPUTED,
        OrderStatus.CONFIRMED,
        OrderStatus.REFUNDED,
    }:
        raise Conflict("Returns can be recorded once an order has been delivered.")
    already = sum(entry.pieces for entry in order.returns)
    if pieces <= 0 or already + pieces > order.pieces:
        raise ValidationFailed(f"Up to {order.pieces - already} more pieces can be returned.")
    cleaned = reason.strip()
    if len(cleaned) < 3:
        raise ValidationFailed("Say why the goods came back.")

    entry = OrderReturn(
        brand_id=order.brand_id,
        pieces=pieces,
        reason=cleaned[:500],
        recorded_by_user_id=actor.id,
    )
    order.returns.append(entry)
    db.flush()
    audit_service.record(
        db,
        action="order.return_recorded",
        entity_type="order",
        entity_id=order.id,
        brand_id=order.brand_id,
        actor_user_id=actor.id,
        actor_role=actor.role,
        after={"pieces": pieces, "reason": entry.reason},
        ip=ip,
    )
    return entry


def complete_after_dispute(db: Session, order: Order, *, actor: User, note: str) -> Order:
    return _complete(db, order, actor=actor, note=note)


def move_to_refunded(db: Session, order: Order, *, actor: User | None, note: str) -> Order:
    return _move(db, order, OrderStatus.REFUNDED, actor=actor, note=note)


# ------------------------------------------------------------------------ cart


def cart_items(db: Session, *, user: User) -> list[CartItem]:
    return list(
        db.scalars(
            select(CartItem).where(CartItem.user_id == user.id).order_by(CartItem.created_at)
        ).all()
    )


def set_cart_item(db: Session, *, user: User, purchase: Purchase) -> CartItem:
    require_buyer(db, user)
    item = db.scalars(
        select(CartItem).where(CartItem.user_id == user.id, CartItem.lot_id == purchase.lot_id)
    ).first()
    if item is None:
        item = CartItem(user_id=user.id, lot_id=purchase.lot_id)
        db.add(item)
    item.whole_lot = purchase.whole_lot
    item.selection = (
        None
        if purchase.whole_lot
        else {
            "lines": [
                {"size": line.size, "color": line.color, "pieces": line.pieces}
                for line in purchase.lines
            ]
        }
    )
    db.flush()
    return item


def purchase_from_cart(item: CartItem) -> Purchase:
    raw: Any = (item.selection or {}).get("lines", [])
    return Purchase(
        lot_id=item.lot_id,
        whole_lot=item.whole_lot,
        lines=tuple(
            LineChoice(size=str(row["size"]), color=str(row["color"]), pieces=int(row["pieces"]))
            for row in raw
        ),
    )


def remove_cart_item(db: Session, *, user: User, lot_id: str) -> None:
    db.execute(delete(CartItem).where(CartItem.user_id == user.id, CartItem.lot_id == lot_id))


# ------------------------------------------------------------------- internals


def _complete(
    db: Session, order: Order, *, actor: User | None, note: str, ip: str | None = None
) -> Order:
    order.confirmed_at = utcnow()
    _move(db, order, OrderStatus.CONFIRMED, actor=actor, note=note, ip=ip)
    _payments().release_for_order(db, order)
    _mark_lot_sold_if_finished(db, order.lot_id, actor=actor)
    return order


def _payments() -> ModuleType:
    """The payment service, which itself depends on this module."""
    from . import payment_service

    return payment_service


def _mark_lot_sold_if_finished(db: Session, lot_id: str, *, actor: User | None) -> None:
    """A lot becomes sold only when nothing can return its stock.

    Sold is terminal, so doing this while an order could still be cancelled
    would strand those pieces.
    """
    lot = db.get(Lot, lot_id)
    if lot is None or lot.available_pieces > 0 or LotStatus(lot.status) != LotStatus.LIVE:
        return
    unfinished = db.scalars(
        select(Order.id).where(Order.lot_id == lot_id, Order.status.not_in(FINISHED)).limit(1)
    ).first()
    if unfinished is None:
        catalog_service.transition(db, lot=lot, to=LotStatus.SOLD, actor=actor)


def _move(
    db: Session,
    order: Order,
    to: OrderStatus,
    *,
    actor: User | None,
    note: str | None = None,
    ip: str | None = None,
) -> Order:
    current = OrderStatus(order.status)
    if to not in ORDER_TRANSITIONS[current]:
        raise Conflict(f"An order that is {current.value} cannot become {to.value}.")

    order.status = to
    if to in RELEASES_STOCK:
        lot = db.scalars(
            select(Lot)
            .where(Lot.id == order.lot_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        ).one()
        lot.reserved_pieces = max(0, lot.reserved_pieces - order.pieces)
    db.flush()

    _record_event(db, order, current, to, actor=actor, note=note)
    audit_service.record(
        db,
        action=f"order.{to.value}",
        entity_type="order",
        entity_id=order.id,
        brand_id=order.brand_id,
        actor_user_id=actor.id if actor else None,
        actor_role=actor.role if actor else None,
        actor_kind=audit_service.ACTOR_USER if actor else audit_service.ACTOR_SYSTEM,
        before={"status": current.value},
        after={"status": to.value},
        note=note,
        ip=ip,
    )
    return order


def _record_event(
    db: Session,
    order: Order,
    from_status: OrderStatus | None,
    to_status: OrderStatus,
    *,
    actor: User | None,
    note: str | None,
) -> None:
    order.events.append(
        OrderEvent(
            brand_id=order.brand_id,
            from_status=from_status,
            to_status=to_status,
            actor_user_id=actor.id if actor else None,
            actor_role=actor.role.value if actor else "system",
            note=note[:500] if note else None,
        )
    )
    db.flush()


def _policy(db: Session, brand_id: str) -> BrandPolicy:
    policy = db.scalars(select(BrandPolicy).where(BrandPolicy.brand_id == brand_id)).first()
    if policy is None:
        raise Conflict("This brand has no commercial terms yet.")
    return policy


def _clean_delivery(delivery: Delivery) -> Delivery:
    city = " ".join(delivery.city.split())
    address = " ".join(delivery.address.split())
    phone = re.sub(r"\D", "", delivery.phone)
    if len(city) < 2:
        raise ValidationFailed("Enter the delivery city.")
    if len(address) < 5:
        raise ValidationFailed("Enter the full delivery address.")
    if not _PHONE.match(phone):
        raise ValidationFailed("Enter an 11 digit mobile number starting with 03.")
    return Delivery(city=city[:80], address=address[:500], phone=phone)


def _new_code(db: Session) -> str:
    for _ in range(12):
        code = "ORD-" + "".join(secrets.choice(_CODE_ALPHABET) for _ in range(8))
        if db.scalars(select(Order.id).where(Order.order_code == code)).first() is None:
            return code
    raise Conflict("Could not allocate an order number. Try again.")


def _aware(value: datetime | None) -> datetime | None:
    """SQLite returns naive datetimes, and they are always UTC here."""
    if value is None or value.tzinfo is not None:
        return value
    return value.replace(tzinfo=UTC)


def is_open_dispute(dispute: Dispute) -> bool:
    return DisputeStatus(dispute.status) in {DisputeStatus.OPEN, DisputeStatus.UNDER_REVIEW}


def manifest_for(db: Session, lot_id: str) -> list[ManifestLine]:
    return list(db.scalars(select(ManifestLine).where(ManifestLine.lot_id == lot_id)).all())
