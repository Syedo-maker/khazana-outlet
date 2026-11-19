"""Courier booking, labels, pickup and tracking."""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Header, Request, Response, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from ...core.errors import NotFound
from ...core.tenancy import assert_owns
from ...models import Order, Shipment, ShipmentEvent, User
from ...models.enums import ShipmentStatus
from ...services import logistics_service, order_service
from ...storage import read_object
from ..deps import CurrentBrand, CurrentPrincipal, Db, Principal, client_ip

router = APIRouter(tags=["logistics"])


class ShipmentEventOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    status: ShipmentStatus
    location: str | None
    note: str | None
    created_at: datetime


class ShipmentOut(BaseModel):
    id: str
    courier: str
    tracking_number: str | None
    status: ShipmentStatus
    cartons: int | None
    weight_kg: float | None
    cost_pkr: int | None = None
    pickup_scheduled_for: datetime | None
    picked_up_at: datetime | None
    delivered_at: datetime | None
    events: list[ShipmentEventOut]


class PickupIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    pickup_at: datetime


def _shipment_out(shipment: Shipment, *, selling: bool) -> ShipmentOut:
    events: list[ShipmentEvent] = shipment.events
    return ShipmentOut(
        id=shipment.id,
        courier=shipment.courier,
        tracking_number=shipment.tracking_number,
        status=shipment.status,
        cartons=shipment.cartons,
        weight_kg=float(shipment.weight_kg) if shipment.weight_kg is not None else None,
        cost_pkr=shipment.cost_pkr if selling else None,
        pickup_scheduled_for=shipment.pickup_scheduled_for,
        picked_up_at=shipment.picked_up_at,
        delivered_at=shipment.delivered_at,
        events=[ShipmentEventOut.model_validate(event) for event in events],
    )


def _actor(db: Session, principal: Principal) -> User:
    user = db.get(User, principal.user_id)
    if user is None:
        raise NotFound("That account no longer exists.")
    return user


def _brand_order(db: Session, principal: Principal, order_id: str) -> Order:
    order = order_service.get_order(db, order_id)
    assert_owns(principal, order.brand_id)
    return order


def _brand_shipment(db: Session, principal: Principal, shipment_id: str) -> Shipment:
    shipment = logistics_service.get_shipment(db, shipment_id)
    assert_owns(principal, shipment.brand_id)
    return shipment


@router.post(
    "/orders/{order_id}/shipments",
    response_model=ShipmentOut,
    status_code=status.HTTP_201_CREATED,
    operation_id="orders_book_shipment",
)
def book_shipment(order_id: str, principal: CurrentBrand, db: Db, request: Request) -> ShipmentOut:
    order = _brand_order(db, principal, order_id)
    shipment = logistics_service.book_shipment(
        db, order=order, actor=_actor(db, principal), ip=client_ip(request)
    )
    db.commit()
    return _shipment_out(shipment, selling=True)


@router.get(
    "/orders/{order_id}/tracking",
    response_model=list[ShipmentOut],
    operation_id="orders_tracking",
)
def order_tracking(order_id: str, principal: CurrentPrincipal, db: Db) -> list[ShipmentOut]:
    order = order_service.get_order(db, order_id)
    selling = principal.is_admin or order.brand_id in principal.brand_ids
    if not selling and order.buyer_user_id != principal.user_id:
        raise NotFound("That order does not exist.")
    return [
        _shipment_out(logistics_service.get_shipment(db, shipment.id), selling=selling)
        for shipment in order.shipments
    ]


@router.put(
    "/shipments/{shipment_id}/pickup",
    response_model=ShipmentOut,
    operation_id="shipments_schedule_pickup",
)
def schedule_pickup(
    shipment_id: str, body: PickupIn, principal: CurrentBrand, db: Db
) -> ShipmentOut:
    shipment = _brand_shipment(db, principal, shipment_id)
    logistics_service.schedule_pickup(db, shipment=shipment, when=body.pickup_at)
    db.commit()
    return _shipment_out(shipment, selling=True)


@router.get(
    "/shipments/{shipment_id}/label",
    operation_id="shipments_label",
    response_class=Response,
)
def shipment_label(shipment_id: str, principal: CurrentBrand, db: Db) -> Response:
    shipment = _brand_shipment(db, principal, shipment_id)
    if shipment.label_key is None:
        raise NotFound("This shipment has no label.")
    return Response(
        content=read_object(shipment.label_key),
        media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="{shipment.tracking_number}.pdf"'},
    )


@router.post(
    "/shipments/{shipment_id}/sandbox-advance",
    response_model=ShipmentOut,
    operation_id="shipments_sandbox_advance",
)
def sandbox_advance(shipment_id: str, principal: CurrentBrand, db: Db) -> ShipmentOut:
    """Play the courier's next step in development. Refused in production."""
    shipment = _brand_shipment(db, principal, shipment_id)
    logistics_service.advance_sandbox(db, shipment=shipment)
    db.commit()
    return _shipment_out(logistics_service.get_shipment(db, shipment_id), selling=True)


@router.post("/shipments/webhooks/{courier}", operation_id="shipments_courier_callback")
async def courier_callback(
    courier: str,
    request: Request,
    db: Db,
    x_sandbox_signature: str | None = Header(default=None),
) -> dict[str, bool]:
    logistics_service.ingest_callback(
        db,
        courier_code=courier,
        body=await request.body(),
        signature=x_sandbox_signature,
    )
    db.commit()
    return {"received": True}
