"""Forecasts for brands and administrators, and the season calendar."""

from __future__ import annotations

from datetime import date, datetime

from fastapi import APIRouter, Query, status
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import select

from ...core.errors import NotFound
from ...core.tenancy import assert_owns
from ...models import Category, DemandForecast, Lot, LotForecast, ProductionWarning, SeasonEvent
from ...models.base import utcnow
from ...services import audit_service, forecast_service
from ..deps import AdminOnly, CurrentBrand, Db

router = APIRouter(tags=["forecasts"])


class EventOut(BaseModel):
    id: str
    name: str
    starts_on: date
    ends_on: date
    lead_days: int
    demand_factor: float
    keywords: list[str]
    note: str


class EventIn(BaseModel):
    name: str = Field(min_length=2, max_length=80)
    starts_on: date
    ends_on: date
    lead_days: int = Field(default=14, ge=0, le=120)
    demand_factor: float = Field(default=1.5, ge=0.1, le=5)
    keywords: list[str] = Field(min_length=1, max_length=20)
    note: str = Field(default="", max_length=300)

    @model_validator(mode="after")
    def _ordered(self) -> EventIn:
        if self.ends_on < self.starts_on:
            raise ValueError("An event cannot end before it starts.")
        return self


class LotForecastOut(BaseModel):
    lot_id: str
    lot_code: str
    title: str
    weekly_pieces: float
    weeks_to_clear: float | None
    at_risk: bool
    reason: str


class WarningOut(BaseModel):
    category: str
    live_pieces: int
    weekly_demand: float
    weeks_of_demand: float | None
    message: str


class BrandForecastOut(BaseModel):
    computed_at: datetime | None
    at_risk: list[LotForecastOut]
    on_track: list[LotForecastOut]
    warnings: list[WarningOut]
    upcoming: list[EventOut]


class DemandOut(BaseModel):
    category: str
    city: str
    week_start: date
    expected_pieces: float
    base_weekly_pieces: float
    factor: float
    events: list[str]


class RunOut(BaseModel):
    forecasts: int
    lots_checked: int
    lots_flagged: int
    warnings: int


def _event_out(event: SeasonEvent) -> EventOut:
    return EventOut(
        id=event.id,
        name=event.name,
        starts_on=event.starts_on,
        ends_on=event.ends_on,
        lead_days=event.lead_days,
        demand_factor=float(event.demand_factor),
        keywords=[str(w) for w in (event.keywords or {}).get("words", [])],
        note=event.note,
    )


@router.get(
    "/brands/{brand_id}/forecast",
    response_model=BrandForecastOut,
    operation_id="brand_forecast",
)
def brand_forecast(brand_id: str, principal: CurrentBrand, db: Db) -> BrandForecastOut:
    """This brand's lots heading nowhere, its over production warnings, and the
    seasons coming up. From the last scheduled run."""
    assert_owns(principal, brand_id)
    rows = db.execute(
        select(LotForecast, Lot)
        .join(Lot, Lot.id == LotForecast.lot_id)
        .where(LotForecast.brand_id == brand_id)
        .order_by(LotForecast.at_risk.desc(), LotForecast.weeks_to_clear.desc())
    ).all()
    lots = [
        LotForecastOut(
            lot_id=lot.id,
            lot_code=lot.lot_code,
            title=lot.title,
            weekly_pieces=float(forecast.weekly_pieces),
            weeks_to_clear=None
            if forecast.weeks_to_clear is None
            else float(forecast.weeks_to_clear),
            at_risk=forecast.at_risk,
            reason=forecast.reason,
        )
        for forecast, lot in rows
    ]
    categories = {c.id: c.name for c in db.scalars(select(Category))}
    warnings = db.scalars(select(ProductionWarning).where(ProductionWarning.brand_id == brand_id))
    computed = [forecast.computed_at for forecast, _ in rows]
    return BrandForecastOut(
        computed_at=max(computed) if computed else None,
        at_risk=[item for item in lots if item.at_risk],
        on_track=[item for item in lots if not item.at_risk],
        warnings=[
            WarningOut(
                category=categories.get(w.category_id, ""),
                live_pieces=w.live_pieces,
                weekly_demand=float(w.weekly_demand),
                weeks_of_demand=None if w.weeks_of_demand is None else float(w.weeks_of_demand),
                message=w.message,
            )
            for w in warnings
        ],
        upcoming=[
            _event_out(e) for e in forecast_service.upcoming_events(db, today=utcnow().date())
        ],
    )


@router.get(
    "/admin/forecast/demand",
    response_model=list[DemandOut],
    operation_id="admin_demand_forecast",
)
def demand(
    _: AdminOnly, db: Db, city: str | None = Query(default=None, max_length=80)
) -> list[DemandOut]:
    """Expected pieces by category and week, for one city or the whole platform."""
    categories = {c.id: c.name for c in db.scalars(select(Category))}
    statement = select(DemandForecast).order_by(
        DemandForecast.week_start, DemandForecast.expected_pieces.desc()
    )
    statement = statement.where(DemandForecast.city == (city or forecast_service.ALL_CITIES))
    return [
        DemandOut(
            category=categories.get(row.category_id, ""),
            city=row.city,
            week_start=row.week_start,
            expected_pieces=float(row.expected_pieces),
            base_weekly_pieces=float(row.base_weekly_pieces),
            factor=float(row.factor),
            events=[str(n) for n in (row.events or {}).get("names", [])],
        )
        for row in db.scalars(statement)
    ]


@router.post("/admin/jobs/forecast", response_model=RunOut, operation_id="admin_run_forecast")
def run_forecast(_: AdminOnly, db: Db) -> RunOut:
    """Run the forecast now. In production a scheduler calls the same function."""
    summary = forecast_service.run(db)
    db.commit()
    return RunOut(
        forecasts=summary.forecasts,
        lots_checked=summary.lots_checked,
        lots_flagged=summary.lots_flagged,
        warnings=summary.warnings,
    )


@router.get("/admin/season-events", response_model=list[EventOut], operation_id="admin_events")
def events(_: AdminOnly, db: Db) -> list[EventOut]:
    rows = db.scalars(select(SeasonEvent).order_by(SeasonEvent.starts_on))
    return [_event_out(e) for e in rows]


@router.post(
    "/admin/season-events",
    response_model=EventOut,
    status_code=status.HTTP_201_CREATED,
    operation_id="admin_add_event",
)
def add_event(body: EventIn, principal: AdminOnly, db: Db) -> EventOut:
    event = SeasonEvent(**{**body.model_dump(), "keywords": {"words": body.keywords}})
    db.add(event)
    db.flush()
    audit_service.record(
        db,
        action="season_event.created",
        entity_type="season_event",
        entity_id=event.id,
        actor_user_id=principal.user_id,
        actor_role=principal.role,
        after=body.model_dump(mode="json"),
    )
    db.commit()
    return _event_out(event)


@router.put(
    "/admin/season-events/{event_id}", response_model=EventOut, operation_id="admin_edit_event"
)
def edit_event(event_id: str, body: EventIn, principal: AdminOnly, db: Db) -> EventOut:
    """Correct an event, for example once Eid's date is announced."""
    event = db.get(SeasonEvent, event_id)
    if event is None:
        raise NotFound("That event does not exist.")
    before = _event_out(event).model_dump(mode="json")
    for name, value in body.model_dump().items():
        setattr(event, name, {"words": value} if name == "keywords" else value)
    db.flush()
    audit_service.record(
        db,
        action="season_event.updated",
        entity_type="season_event",
        entity_id=event.id,
        actor_user_id=principal.user_id,
        actor_role=principal.role,
        before=before,
        after=body.model_dump(mode="json"),
    )
    db.commit()
    return _event_out(event)
