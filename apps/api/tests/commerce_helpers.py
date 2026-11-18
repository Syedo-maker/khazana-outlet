"""Builders shared by the order, payment, logistics and admin tests."""

from __future__ import annotations

from sqlalchemy.orm import Session

from catalog_helpers import build_submitted_lot
from khazana.core.security import create_access_token
from khazana.models import (
    Brand,
    BrandPolicy,
    Courier,
    Lot,
    Order,
    ResellerProfile,
    ShippingRate,
    User,
)
from khazana.models.enums import PaymentMethod, UserRole, VerificationStatus, Visibility
from khazana.services import approval_service, order_service
from khazana.services.order_service import Delivery, LineChoice, Purchase

DELIVERY = Delivery(city="Multan", address="Shop 12, Hussain Agahi", phone="03001234567")
DELIVERY_JSON = {
    "delivery_city": "Multan",
    "delivery_address": "Shop 12, Hussain Agahi",
    "delivery_phone": "03001234567",
}


def auth(user: User) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(user.id, user.role)}"}


def make_reseller(
    db: Session,
    *,
    phone: str = "03007777777",
    city: str = "Multan",
    status: VerificationStatus = VerificationStatus.VERIFIED,
) -> User:
    user = User(phone=phone, full_name="Shop Owner", role=UserRole.RESELLER)
    db.add(user)
    db.flush()
    db.add(
        ResellerProfile(
            user_id=user.id,
            business_name="Multan Cloth House",
            city=city,
            status=status,
        )
    )
    db.commit()
    return user


def make_courier(db: Session) -> Courier:
    courier = Courier(code="sandbox", name="Sandbox courier", is_active=True, is_default=True)
    courier.rates.append(ShippingRate(base_pkr=500, per_kg_pkr=60, default_piece_grams=300))
    db.add(courier)
    db.commit()
    return courier


def policy_for(db: Session, brand: Brand) -> BrandPolicy:
    policy = db.query(BrandPolicy).filter_by(brand_id=brand.id).one()
    return policy


def open_for_part_orders(db: Session, brand: Brand, *, cod: bool = False) -> BrandPolicy:
    policy = policy_for(db, brand)
    policy.allow_part_lot_orders = True
    policy.allow_cod = cod
    policy.min_lot_value_pkr = 0
    db.commit()
    return policy


def live_lot(
    db: Session,
    brand: Brand,
    owner: User,
    category_id: str,
    *,
    offset: int = 0,
    visibility: Visibility = Visibility.PUBLIC,
    **overrides: object,
) -> Lot:
    lot = build_submitted_lot(db, brand, owner, category_id, offset=offset, **overrides)
    approval_service.approve(db, lot=lot, actor=owner, visibility=visibility)
    db.commit()
    return lot


def whole_order(
    db: Session,
    buyer: User,
    lot: Lot,
    *,
    method: PaymentMethod = PaymentMethod.JAZZCASH,
) -> Order:
    orders = order_service.place_orders(
        db,
        buyer=buyer,
        purchases=[Purchase(lot_id=lot.id)],
        delivery=DELIVERY,
        method=method,
    )
    db.commit()
    return orders[0]


def part_order(
    db: Session,
    buyer: User,
    lot: Lot,
    lines: list[tuple[str, str, int]],
    *,
    method: PaymentMethod = PaymentMethod.JAZZCASH,
) -> Order:
    orders = order_service.place_orders(
        db,
        buyer=buyer,
        purchases=[
            Purchase(
                lot_id=lot.id,
                whole_lot=False,
                lines=tuple(LineChoice(size=s, color=c, pieces=p) for s, c, p in lines),
            )
        ],
        delivery=DELIVERY,
        method=method,
    )
    db.commit()
    return orders[0]
