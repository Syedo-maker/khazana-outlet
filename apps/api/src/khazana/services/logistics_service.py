"""Shipping cost, courier booking, pickup and tracking.

Cost and courier choice are read from configuration. Tracking updates drive the
order: a pickup marks it shipped, and a delivery starts the dispute window.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from math import ceil

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from ..core.errors import Conflict, NotFound, ValidationFailed
from ..models import Courier, Lot, Order, Shipment, ShipmentEvent, ShippingRate, User
from ..models.base import utcnow
from ..models.enums import OrderStatus, PaymentMethod, ShipmentStatus
from ..storage import build_key, put_object
from . import audit_service, courier_providers

TRACKING_STEPS: dict[ShipmentStatus, frozenset[ShipmentStatus]] = {
    ShipmentStatus.PENDING_PICKUP: frozenset({ShipmentStatus.PICKED_UP, ShipmentStatus.LOST}),
    ShipmentStatus.PICKED_UP: frozenset(
        {
            ShipmentStatus.IN_TRANSIT,
            ShipmentStatus.DELIVERED,
            ShipmentStatus.RETURNED,
            ShipmentStatus.LOST,
        }
    ),
    ShipmentStatus.IN_TRANSIT: frozenset(
        {ShipmentStatus.DELIVERED, ShipmentStatus.RETURNED, ShipmentStatus.LOST}
    ),
    ShipmentStatus.DELIVERED: frozenset(),
    ShipmentStatus.RETURNED: frozenset(),
    ShipmentStatus.LOST: frozenset(),
}

SANDBOX_NEXT_STEP = {
    ShipmentStatus.PENDING_PICKUP: ShipmentStatus.PICKED_UP,
    ShipmentStatus.PICKED_UP: ShipmentStatus.IN_TRANSIT,
    ShipmentStatus.IN_TRANSIT: ShipmentStatus.DELIVERED,
}


@dataclass(frozen=True, slots=True)
class ShippingQuote:
    courier: Courier
    rate: ShippingRate
    weight_kg: int
    cost_pkr: int


def default_courier(db: Session) -> Courier:
    courier = db.scalars(
        select(Courier)
        .where(Courier.is_active.is_(True), Courier.is_default.is_(True))
        .options(selectinload(Courier.rates))
        .order_by(Courier.code)
    ).first()
    if courier is None:
        raise Conflict("No delivery company is set up yet, so this order cannot be priced.")
    return courier


def has_default_courier(db: Session) -> bool:
    return (
        db.scalars(
            select(Courier.id).where(Courier.is_active.is_(True), Courier.is_default.is_(True))
        ).first()
        is not None
    )


def _same_city(configured: str | None, city: str) -> bool:
    return configured is not None and configured.casefold() == city.casefold()


def _matching_rate(courier: Courier, origin: str, destination: str) -> ShippingRate | None:
    """The most specific active rate for a route."""
    best: tuple[int, ShippingRate] | None = None
    for rate in courier.rates:
        if not rate.is_active:
            continue
        if rate.origin_city is not None and not _same_city(rate.origin_city, origin):
            continue
        if rate.destination_city is not None and not _same_city(rate.destination_city, destination):
            continue
        score = (2 if rate.origin_city else 0) + (1 if rate.destination_city else 0)
        if best is None or score > best[0]:
            best = (score, rate)
    return best[1] if best else None


def quote(db: Session, *, lot: Lot, pieces: int, destination_city: str) -> ShippingQuote:
    courier = default_courier(db)
    rate = _matching_rate(courier, lot.stock_city, destination_city)
    if rate is None:
        raise Conflict(f"Delivery to {destination_city} is not available yet.")

    if lot.weight_kg:
        weight = float(lot.weight_kg) * pieces / lot.total_pieces
    else:
        weight = pieces * rate.default_piece_grams / 1000
    billable_kg = max(1, ceil(weight))
    return ShippingQuote(
        courier=courier,
        rate=rate,
        weight_kg=billable_kg,
        cost_pkr=rate.base_pkr + rate.per_kg_pkr * billable_kg,
    )


def book_shipment(db: Session, *, order: Order, actor: User, ip: str | None = None) -> Shipment:
    """Book the courier for an order the brand has ready to send."""
    from . import direct_service, order_service

    if direct_service.is_direct(order):
        raise Conflict(
            "This brand sends with its own courier. Enter the courier and tracking number instead."
        )
    if OrderStatus(order.status) == OrderStatus.PAID:
        order_service.start_preparing(db, order, actor=actor, ip=ip)
    if OrderStatus(order.status) != OrderStatus.PREPARING:
        raise Conflict("Only an order being prepared can be booked with a courier.")
    if order.shipments:
        raise Conflict("A courier has already been booked for this order.")

    lot = db.get(Lot, order.lot_id)
    if lot is None:
        raise NotFound("That order's lot no longer exists.")
    shipping = quote(db, lot=lot, pieces=order.pieces, destination_city=order.delivery_city)
    cartons = ceil((lot.cartons or 1) * order.pieces / lot.total_pieces)
    is_cod = PaymentMethod(order.payment_method) == PaymentMethod.COD

    provider = courier_providers.provider_for(shipping.courier.code)
    booking = provider.book(
        courier_providers.BookingRequest(
            order_code=order.order_code,
            origin_city=lot.stock_city,
            destination_city=order.delivery_city,
            delivery_address=order.delivery_address,
            delivery_phone=order.delivery_phone,
            cartons=cartons,
            weight_kg=shipping.weight_kg,
            collect_pkr=order.total_pkr if is_cod else 0,
        )
    )
    label_key = build_key(prefix="labels", brand_id=order.brand_id, content_type="application/pdf")
    put_object(label_key, booking.label_pdf, "application/pdf")

    shipment = Shipment(
        brand_id=order.brand_id,
        courier=shipping.courier.code,
        tracking_number=booking.tracking_number,
        status=ShipmentStatus.PENDING_PICKUP,
        cost_pkr=shipping.cost_pkr,
        cartons=cartons,
        weight_kg=shipping.weight_kg,
        label_key=label_key,
    )
    order.shipments.append(shipment)
    db.flush()
    _add_event(db, shipment, ShipmentStatus.PENDING_PICKUP, note="Courier booked.")
    audit_service.record(
        db,
        action="shipment.booked",
        entity_type="shipment",
        entity_id=shipment.id,
        brand_id=order.brand_id,
        actor_user_id=actor.id,
        actor_role=actor.role,
        after={"order": order.order_code, "tracking": booking.tracking_number},
        ip=ip,
    )
    return shipment


def schedule_pickup(db: Session, *, shipment: Shipment, when: datetime) -> Shipment:
    if ShipmentStatus(shipment.status) != ShipmentStatus.PENDING_PICKUP:
        raise Conflict("This shipment has already been collected.")
    moment = when if when.tzinfo else when.replace(tzinfo=UTC)
    if moment <= utcnow():
        raise ValidationFailed("Choose a pickup time in the future.")
    shipment.pickup_scheduled_for = moment
    _add_event(
        db,
        shipment,
        ShipmentStatus.PENDING_PICKUP,
        note=f"Pickup scheduled for {moment:%Y-%m-%d %H:%M} UTC.",
    )
    return shipment


def apply_tracking(
    db: Session,
    *,
    shipment: Shipment,
    status: ShipmentStatus,
    location: str | None = None,
    note: str | None = None,
    provider_event_id: str | None = None,
) -> Shipment:
    """Record a tracking update, and carry its meaning onto the order."""
    from . import order_service

    if provider_event_id is not None and any(
        event.provider_event_id == provider_event_id for event in shipment.events
    ):
        return shipment

    current = ShipmentStatus(shipment.status)
    if status not in TRACKING_STEPS[current]:
        raise Conflict(f"A shipment that is {current.value} cannot become {status.value}.")

    shipment.status = status
    try:
        with db.begin_nested():
            _add_event(
                db,
                shipment,
                status,
                location=location,
                note=note,
                provider_event_id=provider_event_id,
            )
    except IntegrityError:
        return shipment

    order = order_service.get_order(db, shipment.order_id)
    label = f"Tracking {shipment.tracking_number}"
    if status == ShipmentStatus.PICKED_UP:
        shipment.picked_up_at = utcnow()
        order_service.mark_shipped(db, order, note=f"{label}: collected by the courier.")
    elif status == ShipmentStatus.DELIVERED:
        shipment.delivered_at = utcnow()
        if OrderStatus(order.status) == OrderStatus.PREPARING:
            order_service.mark_shipped(db, order, note=label)
        order_service.mark_delivered(db, order, note=f"{label}: delivered.")
    db.flush()
    return shipment


def advance_sandbox(db: Session, *, shipment: Shipment) -> Shipment:
    """Play the courier's next move, through its signed callback."""
    courier = courier_providers.sandbox_courier()
    if shipment.courier != courier.code or shipment.tracking_number is None:
        raise Conflict("This shipment is not with the sandbox courier.")
    step = SANDBOX_NEXT_STEP.get(ShipmentStatus(shipment.status))
    if step is None:
        raise Conflict("This shipment has no further steps.")
    body, signature = courier.build_callback(
        tracking_number=shipment.tracking_number, status=step, location="Sandbox hub"
    )
    ingest_callback(db, courier_code=courier.code, body=body, signature=signature)
    return shipment


def ingest_callback(
    db: Session, *, courier_code: str, body: bytes, signature: str | None
) -> Shipment | None:
    provider = courier_providers.provider_for(courier_code)
    update = provider.parse_callback(body, signature)
    shipment = db.scalars(
        select(Shipment)
        .where(Shipment.courier == courier_code, Shipment.tracking_number == update.tracking_number)
        .options(selectinload(Shipment.events))
        .with_for_update()
    ).first()
    if shipment is None:
        return None
    return apply_tracking(
        db,
        shipment=shipment,
        status=update.status,
        location=update.location,
        note=update.note,
        provider_event_id=update.event_id,
    )


def get_shipment(db: Session, shipment_id: str) -> Shipment:
    shipment = db.scalars(
        select(Shipment).where(Shipment.id == shipment_id).options(selectinload(Shipment.events))
    ).first()
    if shipment is None:
        raise NotFound("That shipment does not exist.")
    return shipment


def _add_event(
    db: Session,
    shipment: Shipment,
    status: ShipmentStatus,
    *,
    location: str | None = None,
    note: str | None = None,
    provider_event_id: str | None = None,
) -> None:
    shipment.events.append(
        ShipmentEvent(
            brand_id=shipment.brand_id,
            status=status,
            location=location[:120] if location else None,
            note=note[:300] if note else None,
            provider_event_id=provider_event_id,
        )
    )
    db.flush()
