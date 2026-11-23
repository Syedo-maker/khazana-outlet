"""The reseller profit helper.

Answers the buyer's real question before they order: if I buy this and sell
it in my city, what do I make?

Arithmetic, not a model. Cost is the lot price for the pieces plus the real
shipping quote to the buyer's city. Resale value comes from a benchmark row an
administrator maintains, as a share of the brand's retail price, in three
scenarios. The buyer can replace the benchmark with their own selling price.
Every estimate lists the assumptions it used, because an estimate a buyer
cannot check is a number they should not trust.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from math import ceil

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..core.errors import AppError, Conflict, NotFound, ValidationFailed
from ..models import Category, Lot, ResaleBenchmark, User
from . import audit_service, logistics_service


@dataclass(slots=True)
class Scenario:
    name: str
    price_per_piece_pkr: int
    revenue_pkr: int
    profit_pkr: int
    margin_percent: float


@dataclass(slots=True)
class ProfitEstimate:
    lot_code: str
    city: str
    pieces: int
    goods_pkr: int
    shipping_pkr: int | None
    cost_pkr: int
    cost_per_piece_pkr: int
    scenarios: list[Scenario]
    break_even_pieces: int | None
    benchmark: str
    assumptions: list[str] = field(default_factory=list)


def benchmark_for(db: Session, *, category_id: str, city: str) -> ResaleBenchmark:
    """The most specific benchmark: category and city, category, city, default."""
    rows = list(db.scalars(select(ResaleBenchmark).order_by(ResaleBenchmark.created_at)))
    wanted_city = city.strip().lower()

    def matches(row: ResaleBenchmark, *, category: bool, by_city: bool) -> bool:
        category_ok = row.category_id == category_id if category else row.category_id is None
        city_ok = (row.city or "").strip().lower() == wanted_city if by_city else row.city is None
        return category_ok and city_ok

    for category, by_city in ((True, True), (True, False), (False, True), (False, False)):
        for row in rows:
            if matches(row, category=category, by_city=by_city):
                return row
    raise Conflict("No resale benchmark is configured. An administrator must add one.")


def _describe(row: ResaleBenchmark, category_name: str) -> str:
    scope = []
    if row.category_id:
        scope.append(category_name)
    if row.city:
        scope.append(row.city)
    where = " in ".join(scope) if scope else "the platform default"
    return (
        f"Resale at {float(row.low_percent):g}% to {float(row.high_percent):g}% of retail, "
        f"typically {float(row.typical_percent):g}%, from {where}"
    )


def estimate(
    db: Session,
    *,
    lot: Lot,
    city: str,
    pieces: int | None = None,
    selling_price_pkr: int | None = None,
) -> ProfitEstimate:
    if not city.strip():
        raise ValidationFailed("Say which city you will sell in.")
    count = pieces or lot.total_pieces
    if count < 1 or count > lot.total_pieces:
        raise ValidationFailed(f"Choose between 1 and {lot.total_pieces} pieces.")
    if selling_price_pkr is not None and selling_price_pkr < 1:
        raise ValidationFailed("A selling price must be at least 1 rupee.")

    unit_price = lot.lot_price_pkr / lot.total_pieces
    goods = round(unit_price * count)
    assumptions = [f"Lot price of Rs {round(unit_price):,} per piece for {count} pieces"]

    shipping: int | None
    try:
        shipping = logistics_service.quote(
            db, lot=lot, pieces=count, destination_city=city
        ).cost_pkr
        assumptions.append(f"Delivery from {lot.stock_city} to {city}: Rs {shipping:,}")
    except AppError as exc:
        shipping = None
        assumptions.append(f"Delivery not included: {exc.message}")
    cost = goods + (shipping or 0)

    category = db.get(Category, lot.category_id)
    category_name = category.name if category else "this category"
    row = benchmark_for(db, category_id=lot.category_id, city=city)
    retail = lot.retail_price_per_piece_pkr
    if selling_price_pkr is not None:
        prices = {"your price": selling_price_pkr}
        benchmark = "Your own selling price"
        assumptions.append(f"Selling at your price of Rs {selling_price_pkr:,} per piece")
    else:
        prices = {
            "low": round(retail * float(row.low_percent) / 100),
            "typical": round(retail * float(row.typical_percent) / 100),
            "high": round(retail * float(row.high_percent) / 100),
        }
        benchmark = _describe(row, category_name)
        assumptions.append(f"Brand retail price of Rs {retail:,} per piece")
        assumptions.append(benchmark)
    assumptions.append("Every piece sells; unsold pieces reduce the profit")

    scenarios = []
    for name, price in prices.items():
        revenue = price * count
        profit = revenue - cost
        scenarios.append(
            Scenario(
                name=name,
                price_per_piece_pkr=price,
                revenue_pkr=revenue,
                profit_pkr=profit,
                margin_percent=round(100 * profit / revenue, 1) if revenue else 0.0,
            )
        )

    middle = scenarios[len(scenarios) // 2].price_per_piece_pkr
    break_even = ceil(cost / middle) if middle > 0 else None
    if break_even is not None and break_even > count:
        break_even = None

    return ProfitEstimate(
        lot_code=lot.lot_code,
        city=city.strip(),
        pieces=count,
        goods_pkr=goods,
        shipping_pkr=shipping,
        cost_pkr=cost,
        cost_per_piece_pkr=round(cost / count),
        scenarios=scenarios,
        break_even_pieces=break_even,
        benchmark=benchmark,
        assumptions=assumptions,
    )


def list_benchmarks(db: Session) -> list[ResaleBenchmark]:
    return list(db.scalars(select(ResaleBenchmark).order_by(ResaleBenchmark.created_at)))


def save_benchmark(
    db: Session,
    *,
    admin: User,
    category_id: str | None,
    city: str | None,
    low_percent: float,
    typical_percent: float,
    high_percent: float,
    note: str = "",
) -> ResaleBenchmark:
    """Create or replace the benchmark for one category and city. Audited."""
    if not 0 < low_percent <= typical_percent <= high_percent <= 100:
        raise ValidationFailed("Percentages must rise from low to high and stay within 100.")
    if category_id is not None and db.get(Category, category_id) is None:
        raise NotFound("That category does not exist.")
    city_value = city.strip() if city and city.strip() else None
    row = next(
        (
            r
            for r in list_benchmarks(db)
            if r.category_id == category_id and (r.city or "").lower() == (city_value or "").lower()
        ),
        None,
    )
    before = None
    if row is None:
        row = ResaleBenchmark(category_id=category_id, city=city_value)
        db.add(row)
    else:
        before = {
            "low_percent": float(row.low_percent),
            "typical_percent": float(row.typical_percent),
            "high_percent": float(row.high_percent),
        }
    row.low_percent = low_percent
    row.typical_percent = typical_percent
    row.high_percent = high_percent
    row.note = note
    db.flush()
    audit_service.record(
        db,
        action="resale_benchmark.saved",
        entity_type="resale_benchmark",
        entity_id=row.id,
        actor_user_id=admin.id,
        actor_role=admin.role,
        before=before,
        after={
            "category_id": category_id,
            "city": city_value,
            "low_percent": low_percent,
            "typical_percent": typical_percent,
            "high_percent": high_percent,
        },
    )
    return row
