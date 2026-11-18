"""Shipping cost and courier choice, both read from configuration."""

from __future__ import annotations

from dataclasses import dataclass
from math import ceil

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from ..core.errors import Conflict
from ..models import Courier, Lot, ShippingRate


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
