"""Cash on delivery, direct to the brand.

The pilot's order mode, chosen per brand by ``BrandPolicy.settlement_mode``.
The platform never holds the buyer's money:

1. The buyer orders, choosing cash on delivery. No payment record is made.
2. The brand books its own courier, outside the platform, and the brand or an
   admin types the courier's name and tracking number in. The order is shipped.
3. The brand, or an admin, records the outcome from the courier: delivered,
   which starts the buyer's window to report a problem, or refused at the
   door, which cancels the order and puts the stock back.
4. Confirmation records the commission the brand owes; the monthly commission
   invoice bills it. See commission_service.

The payment providers and courier integrations are not used and not changed.
Platform settled orders keep using them exactly as before.
"""

from __future__ import annotations

import re

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..core.errors import Conflict, ValidationFailed
from ..models import Order, Shipment, ShipmentEvent, User
from ..models.base import utcnow
from ..models.enums import OrderStatus, SettlementMode, ShipmentStatus
from . import audit_service

# Letters, digits and the separators couriers print on their slips.
_TRACKING = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 ._/-]{3,79}$")
MANUAL_OUTCOMES = frozenset({ShipmentStatus.DELIVERED, ShipmentStatus.RETURNED})


def is_direct(order: Order) -> bool:
    return SettlementMode(order.settlement_mode) == SettlementMode.DIRECT


def require_direct(order: Order) -> None:
    if not is_direct(order):
        raise Conflict(
            "This order is settled through the platform; book it with the integrated courier."
        )


def record_shipment(
    db: Session,
    *,
    order: Order,
    actor: User,
    courier: str,
    tracking_number: str,
    note: str | None = None,
    ip: str | None = None,
) -> Shipment:
    """The brand has handed the goods to its own courier."""
    from . import order_service

    require_direct(order)
    if OrderStatus(order.status) != OrderStatus.PREPARING:
        raise Conflict("Only an order being prepared can be marked as sent.")
    if order.shipments:
        raise Conflict("A tracking number has already been entered for this order.")

    courier_name = " ".join(courier.split())
    tracking = " ".join(tracking_number.split())
    if not 2 <= len(courier_name) <= 40:
        raise ValidationFailed("Enter the courier company's name, for example TCS or Leopards.")
    if not _TRACKING.match(tracking):
        raise ValidationFailed(
            "Enter the tracking number from the courier's slip: letters, digits and dashes."
        )
    duplicate = db.scalars(
        select(Shipment.id).where(
            Shipment.courier == courier_name, Shipment.tracking_number == tracking
        )
    ).first()
    if duplicate is not None:
        raise Conflict("That tracking number is already on another order.")

    shipment = Shipment(
        brand_id=order.brand_id,
        courier=courier_name,
        tracking_number=tracking,
        status=ShipmentStatus.IN_TRANSIT,
        picked_up_at=utcnow(),
    )
    try:
        with db.begin_nested():
            order.shipments.append(shipment)
            db.flush()
    except IntegrityError as error:
        raise Conflict("That tracking number is already on another order.") from error

    _event(db, shipment, ShipmentStatus.IN_TRANSIT, note=note or f"Sent with {courier_name}.")
    order_service.mark_shipped(db, order, note=f"{courier_name} tracking {tracking}.")
    audit_service.record(
        db,
        action="shipment.entered_by_hand",
        entity_type="shipment",
        entity_id=shipment.id,
        brand_id=order.brand_id,
        actor_user_id=actor.id,
        actor_role=actor.role,
        after={"order": order.order_code, "courier": courier_name, "tracking": tracking},
        ip=ip,
    )
    return shipment


def record_outcome(
    db: Session,
    *,
    shipment: Shipment,
    actor: User,
    status: ShipmentStatus,
    note: str | None = None,
    ip: str | None = None,
) -> Shipment:
    """What the courier reported: delivered and paid, or refused at the door."""
    from . import order_service

    order = order_service.get_order(db, shipment.order_id)
    require_direct(order)
    if status not in MANUAL_OUTCOMES:
        raise ValidationFailed("Record the delivery as delivered or returned.")
    if ShipmentStatus(shipment.status) not in {
        ShipmentStatus.PENDING_PICKUP,
        ShipmentStatus.PICKED_UP,
        ShipmentStatus.IN_TRANSIT,
    }:
        raise Conflict(f"This shipment is already {shipment.status}.")

    cleaned = " ".join((note or "").split())[:300] or None
    shipment.status = status
    label = f"{shipment.courier} tracking {shipment.tracking_number}"
    if status == ShipmentStatus.DELIVERED:
        shipment.delivered_at = utcnow()
        _event(db, shipment, status, note=cleaned or "Delivered and paid in cash.")
        order_service.mark_delivered(db, order, note=f"{label}: delivered, cash collected.")
    else:
        _event(db, shipment, status, note=cleaned or "Refused by the buyer.")
        order_service.cancel_refused_delivery(
            db, order, actor=actor, reason=cleaned or f"{label}: refused at delivery.", ip=ip
        )

    audit_service.record(
        db,
        action=f"shipment.{status.value}_by_hand",
        entity_type="shipment",
        entity_id=shipment.id,
        brand_id=order.brand_id,
        actor_user_id=actor.id,
        actor_role=actor.role,
        after={"order": order.order_code, "status": status.value},
        note=cleaned,
        ip=ip,
    )
    db.flush()
    return shipment


def refund_limit(order: Order) -> int:
    """The most a brand can refund the buyer on a direct order: the goods."""
    return order.subtotal_pkr


def _event(db: Session, shipment: Shipment, status: ShipmentStatus, *, note: str) -> None:
    shipment.events.append(
        ShipmentEvent(brand_id=shipment.brand_id, status=status, note=note[:300])
    )
    db.flush()
