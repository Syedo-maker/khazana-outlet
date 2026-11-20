"""The lookups the brand assistant may run.

Every function takes ``brand_id`` as a keyword the caller supplies from the
signed in session, and every query filters on it. The model's plan has no
field for a brand, so no wording of a question can reach another brand's rows.
A lot code from another brand answers exactly like a code that does not exist.

Nothing here writes. A discount question returns the brand's own band and the
price at its edge, computed by code; changing a price stays a human action on
the lot page.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ...models import BrandPolicy, Category, Lot, Order, utcnow
from ...models.enums import LotStatus, OrderStatus

MAX_RESULTS = 8
DEFAULT_MIN_DAYS_LIVE = 21
DEFAULT_DAYS = 30
MAX_DAYS = 730

# Orders that represent a sale. Created and awaiting payment are not sales yet,
# and cancelled or refunded ones are not sales any more.
SOLD_STATUSES = (
    OrderStatus.PAID,
    OrderStatus.PREPARING,
    OrderStatus.SHIPPED,
    OrderStatus.DELIVERED,
    OrderStatus.CONFIRMED,
    OrderStatus.DISPUTED,
)

NOT_FOUND = {"found": False, "note": "No lot with that code belongs to this brand."}


def _aware(value: Any) -> Any:
    # SQLite hands back naive datetimes; PostgreSQL hands back aware ones.
    if value is not None and value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value


def _sold_by_lot(db: Session, brand_id: str, lot_ids: list[str]) -> dict[str, int]:
    if not lot_ids:
        return {}
    rows = db.execute(
        select(Order.lot_id, func.coalesce(func.sum(Order.pieces), 0))
        .where(
            Order.brand_id == brand_id,
            Order.lot_id.in_(lot_ids),
            Order.status.in_(SOLD_STATUSES),
        )
        .group_by(Order.lot_id)
    ).all()
    return {lot_id: int(pieces) for lot_id, pieces in rows}


def _own_lot(db: Session, brand_id: str, lot_code: str) -> Lot | None:
    return db.scalar(
        select(Lot).where(
            Lot.lot_code == lot_code.strip().upper(),
            Lot.brand_id == brand_id,
            Lot.deleted_at.is_(None),
        )
    )


def _price_per_piece(lot: Lot) -> int:
    return round(lot.lot_price_pkr / lot.total_pieces) if lot.total_pieces else 0


def stock_overview(db: Session, *, brand_id: str) -> dict[str, Any]:
    rows = db.execute(
        select(Lot.status, func.count(), func.coalesce(func.sum(Lot.total_pieces), 0))
        .where(Lot.brand_id == brand_id, Lot.deleted_at.is_(None))
        .group_by(Lot.status)
    ).all()
    # EnumText returns the enum, so its value is the readable status name.
    by_status = {LotStatus(status).value: int(count) for status, count, _ in rows}
    live = db.execute(
        select(
            func.coalesce(func.sum(Lot.total_pieces - Lot.reserved_pieces), 0),
            func.coalesce(func.sum(Lot.lot_price_pkr), 0),
        ).where(
            Lot.brand_id == brand_id,
            Lot.status == LotStatus.LIVE,
            Lot.deleted_at.is_(None),
        )
    ).one()
    return {
        "lots_by_status": by_status,
        "live_pieces_available": int(live[0]),
        "live_lot_value_pkr": int(live[1]),
    }


def slow_lots(db: Session, *, brand_id: str, min_days_live: int | None = None) -> dict[str, Any]:
    days = max(1, min(min_days_live or DEFAULT_MIN_DAYS_LIVE, MAX_DAYS))
    now = utcnow()
    cutoff = now - timedelta(days=days)
    lots = list(
        db.scalars(
            select(Lot).where(
                Lot.brand_id == brand_id,
                Lot.status == LotStatus.LIVE,
                Lot.deleted_at.is_(None),
                Lot.approved_at.is_not(None),
                Lot.approved_at <= cutoff,
            )
        )
    )
    sold = _sold_by_lot(db, brand_id, [lot.id for lot in lots])
    rows = []
    for lot in lots:
        pieces_sold = sold.get(lot.id, 0)
        through = round(100 * pieces_sold / lot.total_pieces) if lot.total_pieces else 0
        rows.append(
            {
                "lot_code": lot.lot_code,
                "title": lot.title,
                "days_live": (now - _aware(lot.approved_at)).days,
                "total_pieces": lot.total_pieces,
                "pieces_sold": pieces_sold,
                "sell_through_percent": through,
                "discount_percent": round(lot.discount_percent),
                "stock_city": lot.stock_city,
            }
        )
    # Slowest first: least sold relative to size, then longest on sale.
    rows.sort(key=lambda row: (row["sell_through_percent"], -row["days_live"]))
    return {"min_days_live": days, "count": len(rows), "lots": rows[:MAX_RESULTS]}


def sales_summary(
    db: Session,
    *,
    brand_id: str,
    days: int | None = None,
    city: str | None = None,
    category: str | None = None,
) -> dict[str, Any]:
    window = max(1, min(days or DEFAULT_DAYS, MAX_DAYS))
    since = utcnow() - timedelta(days=window)
    statement = (
        select(Order)
        .join(Lot, Lot.id == Order.lot_id)
        .where(
            Order.brand_id == brand_id,
            Order.status.in_(SOLD_STATUSES),
            Order.created_at >= since,
        )
    )
    if city:
        statement = statement.where(func.lower(Order.delivery_city) == city.strip().lower())
    if category:
        statement = statement.join(Category, Category.id == Lot.category_id).where(
            func.lower(Category.name).contains(category.strip().lower())
        )
    orders = list(db.scalars(statement))

    by_city: dict[str, int] = {}
    by_lot: dict[str, int] = {}
    lot_codes = (
        {
            lot.id: lot.lot_code
            for lot in db.scalars(select(Lot).where(Lot.id.in_({order.lot_id for order in orders})))
        }
        if orders
        else {}
    )
    for order in orders:
        by_city[order.delivery_city] = by_city.get(order.delivery_city, 0) + order.pieces
        code = lot_codes.get(order.lot_id, "")
        by_lot[code] = by_lot.get(code, 0) + order.pieces

    def top(counts: dict[str, int], key: str) -> list[dict[str, Any]]:
        ranked = sorted(counts.items(), key=lambda item: item[1], reverse=True)
        return [{key: name, "pieces": pieces} for name, pieces in ranked[:5]]

    return {
        "days": window,
        "city": city or "all cities",
        "category": category or "all categories",
        "orders": len(orders),
        "pieces": sum(order.pieces for order in orders),
        "goods_value_pkr": sum(order.subtotal_pkr for order in orders),
        "brand_payout_pkr": sum(order.brand_payout_pkr for order in orders),
        "top_cities": top(by_city, "city"),
        "top_lots": top(by_lot, "lot_code"),
    }


def lot_performance(db: Session, *, brand_id: str, lot_code: str) -> dict[str, Any]:
    lot = _own_lot(db, brand_id, lot_code)
    if lot is None:
        return NOT_FOUND
    sold = _sold_by_lot(db, brand_id, [lot.id]).get(lot.id, 0)
    order_count = db.scalar(
        select(func.count())
        .select_from(Order)
        .where(Order.lot_id == lot.id, Order.status.in_(SOLD_STATUSES))
    )
    days_live = (utcnow() - _aware(lot.approved_at)).days if lot.approved_at else None
    return {
        "found": True,
        "lot_code": lot.lot_code,
        "title": lot.title,
        "status": lot.status.value,
        "days_live": days_live,
        "total_pieces": lot.total_pieces,
        "reserved_pieces": lot.reserved_pieces,
        "pieces_sold": sold,
        "orders": int(order_count or 0),
        "price_per_piece_pkr": _price_per_piece(lot),
        "discount_percent": round(lot.discount_percent),
        "stock_city": lot.stock_city,
    }


def discount_room(db: Session, *, brand_id: str, lot_code: str) -> dict[str, Any]:
    lot = _own_lot(db, brand_id, lot_code)
    if lot is None:
        return NOT_FOUND
    policy = db.scalar(select(BrandPolicy).where(BrandPolicy.brand_id == brand_id))
    band_min = float(policy.min_discount_percent) if policy else 50.0
    band_max = float(policy.max_discount_percent) if policy else 85.0
    at_max = round(lot.retail_price_per_piece_pkr * (1 - band_max / 100))
    return {
        "found": True,
        "lot_code": lot.lot_code,
        "discount_percent": round(lot.discount_percent),
        "band_min_percent": round(band_min),
        "band_max_percent": round(band_max),
        "price_per_piece_pkr": _price_per_piece(lot),
        "price_per_piece_at_band_max_pkr": at_max,
        "retail_price_per_piece_pkr": lot.retail_price_per_piece_pkr,
        "note": "Only the brand can change a price, on the lot page.",
    }


ToolFunction = Callable[..., dict[str, Any]]

TOOLS: dict[str, tuple[ToolFunction, set[str]]] = {
    "stock_overview": (stock_overview, set()),
    "slow_lots": (slow_lots, {"min_days_live"}),
    "sales_summary": (sales_summary, {"days", "city", "category"}),
    "lot_performance": (lot_performance, {"lot_code"}),
    "discount_room": (discount_room, {"lot_code"}),
}


def run_tool(db: Session, name: str, arguments: dict[str, Any], *, brand_id: str) -> Any:
    """Run one tool with only the arguments it takes, and the session's brand."""
    function, accepted = TOOLS[name]
    kept = {key: value for key, value in arguments.items() if key in accepted}
    return function(db, brand_id=brand_id, **kept)
