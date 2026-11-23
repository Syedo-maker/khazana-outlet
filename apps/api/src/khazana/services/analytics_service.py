"""Reporting: what sold, what the platform earns, what AI costs, what was saved.

Every figure is computed from the platform's own records when asked for, so a
report cannot drift from the orders it describes. Four reports:

- **Brand**: what this brand sold, where, in which categories, at what price
  and discount, month by month.
- **Platform**: gross merchandise value, orders, commission, active buyers
  and new accounts, against the period before.
- **AI cost**: spend per feature, and the two numbers the Phase 4 exit asks
  for: AI cost per listing and per order.
- **Impact**: pieces sold or given a second life instead of discarded, and
  the weight, water and carbon that represents, with the factors used.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..models import (
    AiJob,
    AiOutput,
    Brand,
    Category,
    ImpactFactor,
    Lot,
    Order,
    Redirection,
    User,
    utcnow,
)
from ..models.enums import (
    SOLD_ORDER_STATUSES,
    AiFeature,
    LotStatus,
    RedirectStatus,
    UserRole,
)

SOLD = SOLD_ORDER_STATUSES
# Which AI features serve a listing and which serve an order, for the two
# unit costs. Features that serve neither, such as the brand assistant and the
# forecasts, count towards the total only.
LISTING_FEATURES = (
    AiFeature.LISTING_FROM_PHOTOS,
    AiFeature.LOGO_DETECTION,
    AiFeature.MANIFEST_EXTRACT,
    AiFeature.PRICING,
    AiFeature.RISK_SCORING,
    AiFeature.MARKDOWN,
)
ORDER_FEATURES = (
    AiFeature.ASSISTANT_BUYER,
    AiFeature.BARGAINING,
    AiFeature.RESELL_KIT,
)


def _sold_orders(
    db: Session, since: datetime, until: datetime, brand_id: str | None = None
) -> list[Order]:
    statement = select(Order).where(
        Order.status.in_(SOLD), Order.created_at >= since, Order.created_at < until
    )
    if brand_id is not None:
        statement = statement.where(Order.brand_id == brand_id)
    return list(db.scalars(statement))


def _top(counts: dict[str, int], key: str, limit: int = 8) -> list[dict[str, Any]]:
    ranked = sorted(counts.items(), key=lambda item: item[1], reverse=True)[:limit]
    return [{key: name, "pieces": pieces} for name, pieces in ranked]


def brand_report(db: Session, *, brand_id: str, days: int = 90) -> dict[str, Any]:
    now = utcnow()
    since = now - timedelta(days=days)
    orders = _sold_orders(db, since, now, brand_id)
    lots = {lot.id: lot for lot in db.scalars(select(Lot).where(Lot.brand_id == brand_id))}
    categories = {c.id: c.name for c in db.scalars(select(Category))}

    by_city: dict[str, int] = defaultdict(int)
    by_category: dict[str, int] = defaultdict(int)
    by_month: dict[str, dict[str, int]] = defaultdict(lambda: {"pieces": 0, "goods_pkr": 0})
    discount_weighted = 0.0
    for order in orders:
        lot = lots.get(order.lot_id)
        by_city[order.delivery_city] += order.pieces
        if lot is not None:
            by_category[categories.get(lot.category_id, "Other")] += order.pieces
            retail = lot.retail_price_per_piece_pkr
            if retail:
                discount_weighted += (1 - order.unit_price_pkr / retail) * 100 * order.pieces
        month = order.created_at.strftime("%Y-%m")
        by_month[month]["pieces"] += order.pieces
        by_month[month]["goods_pkr"] += order.subtotal_pkr

    pieces = sum(o.pieces for o in orders)
    status_counts: dict[str, int] = defaultdict(int)
    for lot in lots.values():
        status_counts[LotStatus(lot.status).value] += 1
    return {
        "days": days,
        "orders": len(orders),
        "pieces": pieces,
        "goods_pkr": sum(o.subtotal_pkr for o in orders),
        "payout_pkr": sum(o.brand_payout_pkr for o in orders),
        "average_price_per_piece_pkr": round(sum(o.subtotal_pkr for o in orders) / pieces)
        if pieces
        else 0,
        "average_discount_percent": round(discount_weighted / pieces, 1) if pieces else 0.0,
        "by_city": _top(by_city, "city"),
        "by_category": _top(by_category, "category"),
        "by_month": [{"month": m, **v} for m, v in sorted(by_month.items())],
        "lots_by_status": dict(status_counts),
    }


@dataclass(slots=True)
class Period:
    gmv_pkr: int = 0
    orders: int = 0
    commission_pkr: int = 0
    active_buyers: int = 0
    new_accounts: int = 0


def _period(db: Session, since: datetime, until: datetime) -> Period:
    orders = _sold_orders(db, since, until)
    new_accounts = db.scalar(
        select(func.count())
        .select_from(User)
        .where(
            User.created_at >= since,
            User.created_at < until,
            User.role.in_([UserRole.RESELLER, UserRole.BRAND]),
        )
    )
    return Period(
        gmv_pkr=sum(o.subtotal_pkr for o in orders),
        orders=len(orders),
        commission_pkr=sum(o.commission_pkr for o in orders),
        active_buyers=len({o.buyer_user_id for o in orders}),
        new_accounts=int(new_accounts or 0),
    )


def _change(now: int, before: int) -> float | None:
    if before == 0:
        return None
    return round((now - before) / before * 100, 1)


def platform_report(db: Session, *, days: int = 30) -> dict[str, Any]:
    now = utcnow()
    current = _period(db, now - timedelta(days=days), now)
    previous = _period(db, now - timedelta(days=2 * days), now - timedelta(days=days))
    brands = db.scalar(select(func.count()).select_from(Brand)) or 0
    live = db.scalar(select(func.count()).select_from(Lot).where(Lot.status == LotStatus.LIVE)) or 0
    return {
        "days": days,
        "gmv_pkr": current.gmv_pkr,
        "orders": current.orders,
        "commission_pkr": current.commission_pkr,
        "active_buyers": current.active_buyers,
        "new_accounts": current.new_accounts,
        "brands": int(brands),
        "live_lots": int(live),
        "change_percent": {
            "gmv": _change(current.gmv_pkr, previous.gmv_pkr),
            "orders": _change(current.orders, previous.orders),
            "active_buyers": _change(current.active_buyers, previous.active_buyers),
            "new_accounts": _change(current.new_accounts, previous.new_accounts),
        },
    }


def ai_costs(db: Session, *, days: int = 30) -> dict[str, Any]:
    now = utcnow()
    since = now - timedelta(days=days)
    rows = db.execute(
        select(
            AiJob.feature,
            func.count(AiOutput.id),
            func.coalesce(func.sum(AiOutput.cost_usd), 0),
            func.coalesce(func.sum(AiOutput.input_tokens), 0),
            func.coalesce(func.sum(AiOutput.output_tokens), 0),
        )
        .join(AiOutput, AiOutput.job_id == AiJob.id)
        .where(AiOutput.created_at >= since)
        .group_by(AiJob.feature)
    ).all()
    features = []
    totals: dict[AiFeature, Decimal] = {}
    for feature, calls, cost, tokens_in, tokens_out in rows:
        value = Decimal(str(cost))
        totals[AiFeature(feature)] = value
        features.append(
            {
                "feature": AiFeature(feature).value,
                "calls": int(calls),
                "cost_usd": str(value.quantize(Decimal("0.0001"))),
                "average_usd": str((value / calls).quantize(Decimal("0.000001"))) if calls else "0",
                "input_tokens": int(tokens_in),
                "output_tokens": int(tokens_out),
            }
        )
    features.sort(key=lambda row: Decimal(row["cost_usd"]), reverse=True)

    listings = db.scalar(select(func.count()).select_from(Lot).where(Lot.created_at >= since)) or 0
    orders = len(_sold_orders(db, since, now))
    listing_cost = sum((totals.get(f, Decimal(0)) for f in LISTING_FEATURES), Decimal(0))
    order_cost = sum((totals.get(f, Decimal(0)) for f in ORDER_FEATURES), Decimal(0))
    total = sum(totals.values(), Decimal(0))

    def per(value: Decimal, count: int) -> str | None:
        return str((value / count).quantize(Decimal("0.0001"))) if count else None

    return {
        "days": days,
        "total_usd": str(total.quantize(Decimal("0.0001"))),
        "features": features,
        "listings": int(listings),
        "orders": orders,
        "cost_per_listing_usd": per(listing_cost, int(listings)),
        "cost_per_order_usd": per(order_cost, orders),
        "listing_features": [f.value for f in LISTING_FEATURES],
        "order_features": [f.value for f in ORDER_FEATURES],
    }


@dataclass(slots=True)
class _Totals:
    pieces: int = 0
    kg: float = 0.0
    water_litres: float = 0.0
    co2_kg: float = 0.0
    factors_used: set[str] = field(default_factory=set)


def _factor_for(category_name: str, factors: list[ImpactFactor]) -> ImpactFactor | None:
    name = category_name.lower()
    for factor in factors:
        if factor.keyword != "*" and factor.keyword.lower() in name:
            return factor
    return next((f for f in factors if f.keyword == "*"), None)


def impact_report(db: Session, *, brand_id: str, days: int = 365) -> dict[str, Any]:
    now = utcnow()
    since = now - timedelta(days=days)
    factors = list(db.scalars(select(ImpactFactor)))
    categories = {c.id: c.name for c in db.scalars(select(Category))}
    lots = {lot.id: lot for lot in db.scalars(select(Lot).where(Lot.brand_id == brand_id))}
    totals = {"sold": _Totals(), "second_life": _Totals()}

    def add(kind: str, lot_id: str, pieces: int) -> None:
        lot = lots.get(lot_id)
        name = categories.get(lot.category_id, "") if lot else ""
        factor = _factor_for(name, factors)
        bucket = totals[kind]
        bucket.pieces += pieces
        if factor is None:
            return
        kg = float(factor.kg_per_piece) * pieces
        bucket.kg += kg
        bucket.water_litres += kg * float(factor.water_litres_per_kg)
        bucket.co2_kg += kg * float(factor.co2_kg_per_kg)
        bucket.factors_used.add(factor.keyword)

    for order in _sold_orders(db, since, now, brand_id):
        add("sold", order.lot_id, order.pieces)
    for row in db.scalars(
        select(Redirection).where(
            Redirection.brand_id == brand_id,
            Redirection.status == RedirectStatus.COLLECTED,
            Redirection.collected_at >= since,
        )
    ):
        add("second_life", row.lot_id, row.pieces)

    def out(bucket: _Totals) -> dict[str, Any]:
        return {
            "pieces": bucket.pieces,
            "kg": round(bucket.kg, 1),
            "water_litres": round(bucket.water_litres),
            "co2_kg": round(bucket.co2_kg, 1),
        }

    used = sorted(totals["sold"].factors_used | totals["second_life"].factors_used)
    return {
        "days": days,
        "sold": out(totals["sold"]),
        "second_life": out(totals["second_life"]),
        "factors": [
            {
                "keyword": f.keyword,
                "kg_per_piece": float(f.kg_per_piece),
                "water_litres_per_kg": float(f.water_litres_per_kg),
                "co2_kg_per_kg": float(f.co2_kg_per_kg),
                "source": f.source,
            }
            for f in factors
            if f.keyword in used
        ],
        "assumption": (
            "Each piece sold as surplus or given a second life is counted as a piece that would "
            "otherwise have been discarded, using the published average factors listed. These "
            "are estimates, not measurements."
        ),
    }
