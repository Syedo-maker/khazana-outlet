"""Cart and orders.

Buyers, brands and admins read the same order through different lenses. A buyer
never receives the commission or a brand identifier, and a brand receives the
delivery details only once it has something to fulfil.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Query, Request, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from ...core.errors import AppError, NotFound, ValidationFailed
from ...models import Dispute, Lot, Order, OrderEvent, OrderReturn, ResellerProfile, User
from ...models.enums import (
    DisputeStatus,
    OrderStatus,
    PaymentMethod,
    SettlementMode,
    UserRole,
)
from ...services import approval_service, direct_service, order_service, payment_service
from ...services.order_service import Delivery, LineChoice, Purchase
from ..deps import CurrentPrincipal, Db, Principal, client_ip

router = APIRouter(tags=["orders"])

# A brand needs the address only once there is something to send.
DETAILS_VISIBLE_TO_BRAND = frozenset(
    {
        OrderStatus.PAID,
        OrderStatus.PREPARING,
        OrderStatus.SHIPPED,
        OrderStatus.DELIVERED,
        OrderStatus.DISPUTED,
        OrderStatus.CONFIRMED,
    }
)


class LineIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    size: str = Field(min_length=1, max_length=32)
    color: str = Field(min_length=1, max_length=48)
    pieces: int = Field(gt=0)


class PurchaseIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    lot_id: str
    whole_lot: bool = True
    lines: list[LineIn] = Field(default_factory=list, max_length=500)


class CartItemIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    whole_lot: bool = True
    lines: list[LineIn] = Field(default_factory=list, max_length=500)


class DeliveryIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    delivery_city: str = Field(min_length=2, max_length=80)
    delivery_address: str = Field(min_length=5, max_length=500)
    delivery_phone: str = Field(min_length=10, max_length=20)
    payment_method: PaymentMethod


class OrderIn(DeliveryIn):
    purchase: PurchaseIn


class QuoteIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    purchase: PurchaseIn
    delivery_city: str = Field(min_length=2, max_length=80)


class ReasonIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: str = Field(min_length=3, max_length=500)


class DisputeIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: str = Field(min_length=3, max_length=120)
    detail: str | None = Field(default=None, max_length=4_000)


class ReturnIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    pieces: int = Field(gt=0)
    reason: str = Field(min_length=3, max_length=500)


class QuoteOut(BaseModel):
    pieces: int
    unit_price_pkr: int
    subtotal_pkr: int
    shipping_pkr: int
    total_pkr: int


class OrderLineOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    size: str
    color: str
    pieces: int
    unit_price_pkr: int


class OrderEventOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    from_status: OrderStatus | None
    to_status: OrderStatus
    actor_role: str
    note: str | None
    created_at: datetime


class OrderReturnOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    pieces: int
    reason: str
    created_at: datetime


class DisputeOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    reason: str
    detail: str | None
    status: DisputeStatus
    resolution: str | None
    refund_pkr: int | None
    created_at: datetime
    resolved_at: datetime | None


class OrderOut(BaseModel):
    id: str
    order_code: str
    lot_id: str
    lot_code: str
    lot_title: str
    seller_name: str
    status: OrderStatus
    payment_method: PaymentMethod
    # "direct": the buyer pays the brand's own courier in cash on delivery,
    # and the platform holds nothing. "platform": paid to the platform first.
    settlement_mode: SettlementMode
    pieces: int
    unit_price_pkr: int
    rounding_adjustment_pkr: int
    subtotal_pkr: int
    shipping_pkr: int
    total_pkr: int
    delivery_city: str
    created_at: datetime
    delivered_at: datetime | None
    dispute_window_ends_at: datetime | None
    confirmed_at: datetime | None
    cancelled_at: datetime | None
    cancellation_reason: str | None
    lines: list[OrderLineOut]
    # The buyer, and the brand once the order is ready to fulfil.
    delivery_address: str | None = None
    delivery_phone: str | None = None
    # The brand and admins only.
    commission_percent: float | None = None
    commission_pkr: int | None = None
    brand_payout_pkr: int | None = None
    buyer_business_name: str | None = None
    # Direct orders, the brand and admins only: what the brand owes once the
    # order is confirmed, and the monthly invoice that bills it.
    commission_due_pkr: int | None = None
    commission_invoice_id: str | None = None


class OrderDetailOut(OrderOut):
    events: list[OrderEventOut]
    disputes: list[DisputeOut]
    returns: list[OrderReturnOut]


class CartItemOut(BaseModel):
    lot_id: str
    lot_code: str | None = None
    title: str | None = None
    seller_name: str | None = None
    whole_lot: bool
    lines: list[LineIn]
    pieces: int | None = None
    subtotal_pkr: int | None = None
    shipping_pkr: int | None = None
    total_pkr: int | None = None
    # Why this item cannot currently be bought, when that is the case.
    problem: str | None = None
    # The buyer pays this brand's own courier in cash on delivery.
    pays_brand_directly: bool = False


class CartOut(BaseModel):
    items: list[CartItemOut]
    delivery_city: str | None
    total_pkr: int
    # Some item is paid to the brand on delivery, so checkout offers cash on
    # delivery only.
    cash_on_delivery_only: bool = False


def _user(db: Session, principal: Principal) -> User:
    user = db.get(User, principal.user_id)
    if user is None:
        raise NotFound("That account no longer exists.")
    return user


def _purchase(body: PurchaseIn) -> Purchase:
    return Purchase(
        lot_id=body.lot_id,
        whole_lot=body.whole_lot,
        lines=tuple(
            LineChoice(size=line.size, color=line.color, pieces=line.pieces) for line in body.lines
        ),
    )


def _accessible(db: Session, principal: Principal, order_id: str) -> Order:
    order = order_service.get_order(db, order_id)
    if (
        principal.is_admin
        or order.buyer_user_id == principal.user_id
        or order.brand_id in principal.brand_ids
    ):
        return order
    raise NotFound("That order does not exist.")


def _open_payment(db: Session, order: Order) -> None:
    """Start the platform payment, unless the brand's courier collects it."""
    if not direct_service.is_direct(order):
        payment_service.ensure_payment(db, order)


def _selling_side(principal: Principal, order: Order) -> bool:
    return principal.is_admin or order.brand_id in principal.brand_ids


@dataclass(slots=True)
class _Related:
    """Lots and buyers for a page of orders, loaded together.

    Held for the length of the request so the identity map, which keeps
    objects only weakly, cannot drop them between rows.
    """

    lots: dict[str, Lot]
    buyers: dict[str, User]


def _related(db: Session, orders: list[Order]) -> _Related:
    """One query for the lots, one for the buyers and their profiles, one for
    the brands, instead of four per order. A brand's list of 50 orders was 204
    queries; it is now a handful whatever its length."""
    lot_ids = {order.lot_id for order in orders}
    buyer_ids = {order.buyer_user_id for order in orders}
    lots = {lot.id: lot for lot in db.scalars(select(Lot).where(Lot.id.in_(lot_ids)))}
    buyers = {
        user.id: user
        for user in db.scalars(
            select(User).where(User.id.in_(buyer_ids)).options(selectinload(User.reseller_profile))
        )
    }
    approval_service.preload_brands(db, lots.values())
    return _Related(lots=lots, buyers=buyers)


def order_payload(
    db: Session, principal: Principal, order: Order, related: _Related | None = None
) -> dict[str, object]:
    lot = related.lots.get(order.lot_id) if related else db.get(Lot, order.lot_id)
    if lot is None:
        raise NotFound("That order's lot no longer exists.")
    shown = approval_service.present(
        db, lot, viewer_role=principal.role, viewer_brand_ids=principal.brand_ids
    )
    selling = _selling_side(principal, order)
    is_buyer = order.buyer_user_id == principal.user_id

    payload: dict[str, object] = {
        "id": order.id,
        "order_code": order.order_code,
        "lot_id": order.lot_id,
        "lot_code": lot.lot_code,
        "lot_title": lot.title,
        "seller_name": shown.brand_name,
        "status": order.status,
        "payment_method": order.payment_method,
        "settlement_mode": order.settlement_mode,
        "pieces": order.pieces,
        "unit_price_pkr": order.unit_price_pkr,
        "rounding_adjustment_pkr": order.rounding_adjustment_pkr,
        "subtotal_pkr": order.subtotal_pkr,
        "shipping_pkr": order.shipping_pkr,
        "total_pkr": order.total_pkr,
        "delivery_city": order.delivery_city,
        "created_at": order.created_at,
        "delivered_at": order.delivered_at,
        "dispute_window_ends_at": order.dispute_window_ends_at,
        "confirmed_at": order.confirmed_at,
        "cancelled_at": order.cancelled_at,
        "cancellation_reason": order.cancellation_reason,
        "lines": [OrderLineOut.model_validate(line) for line in order.lines],
    }

    can_see_delivery = (
        is_buyer
        or principal.is_admin
        or (selling and OrderStatus(order.status) in DETAILS_VISIBLE_TO_BRAND)
    )
    if can_see_delivery:
        payload["delivery_address"] = order.delivery_address
        payload["delivery_phone"] = order.delivery_phone
    if selling:
        buyer = (
            related.buyers.get(order.buyer_user_id)
            if related
            else db.get(User, order.buyer_user_id)
        )
        profile: ResellerProfile | None = buyer.reseller_profile if buyer else None
        payload.update(
            commission_percent=float(order.commission_percent),
            commission_pkr=order.commission_pkr,
            brand_payout_pkr=order.brand_payout_pkr,
            buyer_business_name=profile.business_name if profile else None,
            commission_due_pkr=order.commission_due_pkr,
            commission_invoice_id=order.commission_invoice_id,
        )
    return payload


def _detail(db: Session, principal: Principal, order: Order) -> OrderDetailOut:
    events: list[OrderEvent] = order.events
    disputes: list[Dispute] = order.disputes
    returns: list[OrderReturn] = order.returns
    return OrderDetailOut.model_validate(
        {
            **order_payload(db, principal, order),
            "events": [OrderEventOut.model_validate(item) for item in events],
            "disputes": [DisputeOut.model_validate(item) for item in disputes],
            "returns": [OrderReturnOut.model_validate(item) for item in returns],
        }
    )


def _delivery(body: DeliveryIn) -> Delivery:
    return Delivery(
        city=body.delivery_city,
        address=body.delivery_address,
        phone=body.delivery_phone,
    )


# ------------------------------------------------------------------------ cart


@router.get("/cart", response_model=CartOut, operation_id="cart_view")
def view_cart(
    principal: CurrentPrincipal,
    db: Db,
    delivery_city: Annotated[str | None, Query(max_length=80)] = None,
) -> CartOut:
    """The cart, priced for a delivery city. Nothing is reserved yet."""
    user = _user(db, principal)
    profile = user.reseller_profile
    city = delivery_city or (profile.city if profile else None)

    items: list[CartItemOut] = []
    total = 0
    for row in order_service.cart_items(db, user=user):
        purchase = order_service.purchase_from_cart(row)
        item = CartItemOut(
            lot_id=row.lot_id,
            whole_lot=row.whole_lot,
            lines=[
                LineIn(size=line.size, color=line.color, pieces=line.pieces)
                for line in purchase.lines
            ],
        )
        try:
            if city is None:
                raise ValidationFailed("Choose a delivery city.")
            lot = order_service.buyable_lot(db, lot_id=row.lot_id, city=city)
            shown = approval_service.present(
                db, lot, viewer_role=principal.role, viewer_brand_ids=principal.brand_ids
            )
            item.lot_code = lot.lot_code
            item.title = lot.title
            item.seller_name = shown.brand_name
            item.pays_brand_directly = order_service.brand_is_paid_directly(db, lot.brand_id)
            pricing = order_service.price_purchase(
                db, lot=lot, purchase=purchase, destination_city=city
            )
            item.pieces = pricing.pieces
            item.subtotal_pkr = pricing.subtotal_pkr
            item.shipping_pkr = pricing.shipping_pkr
            item.total_pkr = pricing.total_pkr
            total += pricing.total_pkr
        except AppError as exc:
            item.problem = exc.message
        items.append(item)
    return CartOut(
        items=items,
        delivery_city=city,
        total_pkr=total,
        cash_on_delivery_only=any(item.pays_brand_directly for item in items),
    )


@router.put(
    "/cart/items/{lot_id}",
    response_model=CartItemOut,
    operation_id="cart_set_item",
)
def set_cart_item(
    lot_id: str, body: CartItemIn, principal: CurrentPrincipal, db: Db
) -> CartItemOut:
    user = _user(db, principal)
    purchase = _purchase(PurchaseIn(lot_id=lot_id, whole_lot=body.whole_lot, lines=body.lines))
    # The lot must be one this buyer can see, or the cart would confirm it exists.
    profile = user.reseller_profile
    order_service.require_buyer(db, user)
    order_service.buyable_lot(db, lot_id=lot_id, city=profile.city if profile else "")
    row = order_service.set_cart_item(db, user=user, purchase=purchase)
    db.commit()
    return CartItemOut(lot_id=row.lot_id, whole_lot=row.whole_lot, lines=body.lines)


@router.delete(
    "/cart/items/{lot_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    operation_id="cart_remove_item",
)
def remove_cart_item(lot_id: str, principal: CurrentPrincipal, db: Db) -> None:
    order_service.remove_cart_item(db, user=_user(db, principal), lot_id=lot_id)
    db.commit()


@router.post(
    "/cart/checkout",
    response_model=list[OrderOut],
    status_code=status.HTTP_201_CREATED,
    operation_id="cart_checkout",
)
def checkout(
    body: DeliveryIn, principal: CurrentPrincipal, db: Db, request: Request
) -> list[OrderOut]:
    """Turn the cart into orders, one per lot, all of them or none."""
    user = _user(db, principal)
    purchases = [
        order_service.purchase_from_cart(row) for row in order_service.cart_items(db, user=user)
    ]
    orders = order_service.place_orders(
        db,
        buyer=user,
        purchases=purchases,
        delivery=_delivery(body),
        method=body.payment_method,
        ip=client_ip(request),
    )
    for order in orders:
        _open_payment(db, order)
    db.commit()
    return [OrderOut.model_validate(order_payload(db, principal, order)) for order in orders]


# ---------------------------------------------------------------------- orders


@router.post("/orders/quote", response_model=QuoteOut, operation_id="orders_quote")
def quote_order(body: QuoteIn, principal: CurrentPrincipal, db: Db) -> QuoteOut:
    """What this purchase would cost, delivered. Reserves nothing."""
    user = _user(db, principal)
    order_service.require_buyer(db, user)
    lot = order_service.buyable_lot(db, lot_id=body.purchase.lot_id, city=body.delivery_city)
    pricing = order_service.price_purchase(
        db,
        lot=lot,
        purchase=_purchase(body.purchase),
        destination_city=body.delivery_city,
    )
    return QuoteOut(
        pieces=pricing.pieces,
        unit_price_pkr=pricing.unit_price_pkr,
        subtotal_pkr=pricing.subtotal_pkr,
        shipping_pkr=pricing.shipping_pkr,
        total_pkr=pricing.total_pkr,
    )


@router.post(
    "/orders",
    response_model=OrderDetailOut,
    status_code=status.HTTP_201_CREATED,
    operation_id="orders_create",
)
def create_order(
    body: OrderIn, principal: CurrentPrincipal, db: Db, request: Request
) -> OrderDetailOut:
    orders = order_service.place_orders(
        db,
        buyer=_user(db, principal),
        purchases=[_purchase(body.purchase)],
        delivery=_delivery(body),
        method=body.payment_method,
        ip=client_ip(request),
    )
    _open_payment(db, orders[0])
    db.commit()
    return _detail(db, principal, order_service.get_order(db, orders[0].id))


@router.get("/orders", response_model=list[OrderOut], operation_id="orders_list")
def list_orders(
    principal: CurrentPrincipal,
    db: Db,
    order_status: Annotated[OrderStatus | None, Query(alias="status")] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[OrderOut]:
    """A buyer's purchases, a brand's sales, or everything for an admin."""
    buyer_id: str | None = None
    brand_ids: list[str] | None = None
    if principal.role == UserRole.BRAND:
        brand_ids = principal.brand_ids
    elif not principal.is_admin:
        buyer_id = principal.user_id

    orders = order_service.list_orders(
        db,
        buyer_user_id=buyer_id,
        brand_ids=brand_ids,
        status=order_status,
        limit=limit,
        offset=offset,
    )
    related = _related(db, orders)
    return [
        OrderOut.model_validate(order_payload(db, principal, order, related)) for order in orders
    ]


@router.get("/orders/{order_id}", response_model=OrderDetailOut, operation_id="orders_detail")
def get_order(order_id: str, principal: CurrentPrincipal, db: Db) -> OrderDetailOut:
    return _detail(db, principal, _accessible(db, principal, order_id))


@router.post(
    "/orders/{order_id}/cancel",
    response_model=OrderDetailOut,
    operation_id="orders_cancel",
)
def cancel_order(
    order_id: str, body: ReasonIn, principal: CurrentPrincipal, db: Db, request: Request
) -> OrderDetailOut:
    order = _accessible(db, principal, order_id)
    order_service.cancel(
        db, order, actor=_user(db, principal), reason=body.reason, ip=client_ip(request)
    )
    db.commit()
    return _detail(db, principal, order)


@router.post(
    "/orders/{order_id}/prepare",
    response_model=OrderDetailOut,
    operation_id="orders_prepare",
)
def prepare_order(
    order_id: str, principal: CurrentPrincipal, db: Db, request: Request
) -> OrderDetailOut:
    """The brand starts packing a paid order."""
    order = _accessible(db, principal, order_id)
    if not _selling_side(principal, order):
        raise NotFound("That order does not exist.")
    order_service.start_preparing(db, order, actor=_user(db, principal), ip=client_ip(request))
    db.commit()
    return _detail(db, principal, order)


@router.post(
    "/orders/{order_id}/confirm",
    response_model=OrderDetailOut,
    operation_id="orders_confirm_delivery",
)
def confirm_order(
    order_id: str, principal: CurrentPrincipal, db: Db, request: Request
) -> OrderDetailOut:
    """The buyer accepts the goods, which ends the dispute window early."""
    order = _accessible(db, principal, order_id)
    if order.buyer_user_id != principal.user_id:
        raise NotFound("That order does not exist.")
    order_service.confirm_delivery(db, order, actor=_user(db, principal), ip=client_ip(request))
    db.commit()
    return _detail(db, principal, order)


@router.post(
    "/orders/{order_id}/disputes",
    response_model=OrderDetailOut,
    status_code=status.HTTP_201_CREATED,
    operation_id="orders_open_dispute",
)
def open_dispute(
    order_id: str, body: DisputeIn, principal: CurrentPrincipal, db: Db, request: Request
) -> OrderDetailOut:
    order = _accessible(db, principal, order_id)
    if order.buyer_user_id != principal.user_id:
        raise NotFound("That order does not exist.")
    order_service.open_dispute(
        db,
        order,
        actor=_user(db, principal),
        reason=body.reason,
        detail=body.detail,
        ip=client_ip(request),
    )
    db.commit()
    return _detail(db, principal, order)


@router.post(
    "/orders/{order_id}/returns",
    response_model=OrderDetailOut,
    status_code=status.HTTP_201_CREATED,
    operation_id="orders_record_return",
)
def record_return(
    order_id: str, body: ReturnIn, principal: CurrentPrincipal, db: Db, request: Request
) -> OrderDetailOut:
    order = _accessible(db, principal, order_id)
    if not _selling_side(principal, order):
        raise NotFound("That order does not exist.")
    order_service.record_return(
        db,
        order,
        actor=_user(db, principal),
        pieces=body.pieces,
        reason=body.reason,
        ip=client_ip(request),
    )
    db.commit()
    return _detail(db, principal, order)
