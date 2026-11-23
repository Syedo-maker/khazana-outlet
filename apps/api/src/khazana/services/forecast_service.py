"""Demand and dead stock prediction, run as a scheduled batch job.

Statistics, not a language model. A brand plans production around these
numbers, and AI is never allowed to quote stock or demand figures, so every
number here is arithmetic over the platform's own sales a brand can check:

- **Base demand** for a category in a city is the pieces sold there over the
  last eight weeks, per week.
- **Seasonality** multiplies it by the strongest season event that covers
  the week, from the calendar an administrator maintains. An event starts
  lifting demand ``lead_days`` before it begins.
- **Dead stock**: a live lot's selling rate is its own rate or its fair share
  of its category's rate, whichever is higher. A lot with no rate after four
  weeks live, or more than half a year from clearing, is flagged.
- **Over production**: a brand holding more than half a year of the
  platform's demand for a category gets a warning with the numbers.

The forecasts only ever inform. Nothing here changes a price, a listing or an
order.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timedelta

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from ..models import (
    Category,
    DemandForecast,
    Lot,
    LotForecast,
    Order,
    ProductionWarning,
    SeasonEvent,
    utcnow,
)
from ..models.base import as_utc
from ..models.enums import SOLD_ORDER_STATUSES, LotStatus

HISTORY_WEEKS = 8
FORECAST_WEEKS = 4
STUCK_AFTER_DAYS = 28
TOO_SLOW_WEEKS = 26
ALL_CITIES = "All cities"
SOLD = SOLD_ORDER_STATUSES


@dataclass(slots=True)
class RunSummary:
    forecasts: int
    lots_flagged: int
    lots_checked: int
    warnings: int


def _aware(value: datetime | None) -> datetime | None:
    return None if value is None else as_utc(value)


def week_start(day: date) -> date:
    return day - timedelta(days=day.weekday())


def season_factor(
    events: list[SeasonEvent], category_name: str, week: date
) -> tuple[float, list[str]]:
    """The strongest event lifting this category in the week starting ``week``."""
    name = category_name.lower()
    week_end = week + timedelta(days=6)
    best = 1.0
    names: list[str] = []
    for event in events:
        words = [str(w).lower() for w in (event.keywords or {}).get("words", [])]
        if not any(word in name for word in words):
            continue
        rising = event.starts_on - timedelta(days=event.lead_days)
        if rising <= week_end and event.ends_on >= week:
            names.append(event.name)
            best = max(best, float(event.demand_factor))
    return best, names


def run(db: Session, *, now: datetime | None = None) -> RunSummary:
    moment = now or utcnow()
    since = moment - timedelta(weeks=HISTORY_WEEKS)
    categories = {c.id: c for c in db.scalars(select(Category))}
    events = list(db.scalars(select(SeasonEvent)))

    sold_orders = db.execute(
        select(Order.lot_id, Order.delivery_city, Order.pieces, Lot.category_id)
        .join(Lot, Lot.id == Order.lot_id)
        .where(Order.status.in_(SOLD), Order.created_at >= since)
    ).all()

    by_city: dict[tuple[str, str], int] = defaultdict(int)
    by_category: dict[str, int] = defaultdict(int)
    by_lot: dict[str, int] = defaultdict(int)
    for lot_id, city, pieces, category_id in sold_orders:
        by_city[(category_id, city)] += pieces
        by_category[category_id] += pieces
        by_lot[lot_id] += pieces

    # 1. Demand forecasts, per city and for the whole platform.
    db.execute(delete(DemandForecast))
    first_week = week_start(moment.date() + timedelta(days=7))
    keys = [(cat, city) for cat, city in by_city] + [(cat, ALL_CITIES) for cat in by_category]
    written = 0
    for category_id, city in keys:
        total = by_category[category_id] if city == ALL_CITIES else by_city[(category_id, city)]
        base = total / HISTORY_WEEKS
        category = categories.get(category_id)
        for offset in range(FORECAST_WEEKS):
            week = first_week + timedelta(weeks=offset)
            factor, names = season_factor(events, category.name if category else "", week)
            db.add(
                DemandForecast(
                    category_id=category_id,
                    city=city,
                    week_start=week,
                    expected_pieces=round(base * factor, 2),
                    base_weekly_pieces=round(base, 2),
                    factor=factor,
                    events={"names": names},
                    computed_at=moment,
                )
            )
            written += 1

    # 2. Dead stock flags for every live lot.
    db.execute(delete(LotForecast))
    # A lot with every piece reserved or sold has nothing left to be stuck with.
    live = [
        lot
        for lot in db.scalars(
            select(Lot).where(Lot.status == LotStatus.LIVE, Lot.deleted_at.is_(None))
        )
        if lot.available_pieces > 0
    ]
    live_per_category: dict[str, int] = defaultdict(int)
    for lot in live:
        live_per_category[lot.category_id] += 1
    flagged = 0
    for lot in live:
        own_rate = by_lot.get(lot.id, 0) / HISTORY_WEEKS
        share = by_category.get(lot.category_id, 0) / HISTORY_WEEKS
        share /= max(1, live_per_category[lot.category_id])
        rate = max(own_rate, share)
        available = lot.available_pieces
        approved = _aware(lot.approved_at) or moment
        days_live = (moment - approved).days
        weeks = round(available / rate, 1) if rate > 0 else None
        category_name = categories[lot.category_id].name if lot.category_id in categories else ""
        if rate == 0 and days_live >= STUCK_AFTER_DAYS:
            at_risk = True
            reason = (
                f"No {category_name} has sold on the platform in {HISTORY_WEEKS} weeks and this "
                f"lot has been live for {days_live} days."
            )
        elif weeks is not None and weeks > TOO_SLOW_WEEKS:
            at_risk = True
            reason = (
                f"At about {rate:.1f} pieces a week, the {available} pieces left would take "
                f"{weeks:.0f} weeks to sell."
            )
        else:
            at_risk = False
            reason = (
                f"About {rate:.1f} pieces a week; clears in {weeks:.0f} weeks."
                if weeks is not None
                else "Too new to judge."
            )
        flagged += at_risk
        db.add(
            LotForecast(
                lot_id=lot.id,
                brand_id=lot.brand_id,
                weekly_pieces=round(rate, 2),
                weeks_to_clear=weeks,
                at_risk=at_risk,
                reason=reason,
                computed_at=moment,
            )
        )

    # 3. Over production warnings per brand and category.
    db.execute(delete(ProductionWarning))
    held: dict[tuple[str, str], int] = defaultdict(int)
    for lot in live:
        held[(lot.brand_id, lot.category_id)] += lot.available_pieces
    warnings = 0
    for (brand_id, category_id), pieces in held.items():
        weekly = by_category.get(category_id, 0) / HISTORY_WEEKS
        weeks_of_demand = round(pieces / weekly, 1) if weekly > 0 else None
        if weeks_of_demand is not None and weeks_of_demand <= TOO_SLOW_WEEKS:
            continue
        name = categories[category_id].name if category_id in categories else "this category"
        message = (
            f"You have {pieces} pieces of {name} live. The whole platform sells about "
            f"{weekly:.1f} a week, so that is {weeks_of_demand:.0f} weeks of demand."
            if weeks_of_demand is not None
            else f"You have {pieces} pieces of {name} live and none has sold on the platform "
            f"in {HISTORY_WEEKS} weeks."
        )
        db.add(
            ProductionWarning(
                brand_id=brand_id,
                category_id=category_id,
                live_pieces=pieces,
                weekly_demand=round(weekly, 2),
                weeks_of_demand=weeks_of_demand,
                message=message,
                computed_at=moment,
            )
        )
        warnings += 1

    db.flush()
    return RunSummary(
        forecasts=written, lots_flagged=flagged, lots_checked=len(live), warnings=warnings
    )


def upcoming_events(db: Session, *, today: date, days: int = 90) -> list[SeasonEvent]:
    horizon = today + timedelta(days=days)
    return list(
        db.scalars(
            select(SeasonEvent)
            .where(SeasonEvent.ends_on >= today, SeasonEvent.starts_on <= horizon)
            .order_by(SeasonEvent.starts_on)
        )
    )
