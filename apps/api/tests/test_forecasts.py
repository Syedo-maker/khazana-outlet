"""Demand and dead stock prediction, from sales history and the season calendar."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from commerce_helpers import auth, live_lot, make_courier, make_reseller, whole_order
from khazana.models import AuditLog, DemandForecast, LotForecast, SeasonEvent
from khazana.models.enums import OrderStatus
from khazana.services import forecast_service

NOW = datetime(2026, 11, 20, 9, 0, tzinfo=UTC)


def _event(db: Session, **overrides: object) -> SeasonEvent:
    values: dict[str, object] = {
        "name": "Eid ul Fitr",
        "starts_on": date(2026, 12, 10),
        "ends_on": date(2026, 12, 12),
        "lead_days": 21,
        "demand_factor": 2.0,
        "keywords": {"words": ["womenswear"]},
    }
    values.update(overrides)
    event = SeasonEvent(**values)
    db.add(event)
    db.commit()
    return event


class TestSeasonFactor:
    def test_an_event_lifts_matching_categories_from_its_lead_time(self, db: Session) -> None:
        event = _event(db)
        week_before_lead = forecast_service.week_start(date(2026, 11, 9))
        in_lead = forecast_service.week_start(date(2026, 11, 23))
        assert forecast_service.season_factor([event], "Womenswear stitched", week_before_lead) == (
            1.0,
            [],
        )
        assert forecast_service.season_factor([event], "Womenswear stitched", in_lead) == (
            2.0,
            ["Eid ul Fitr"],
        )
        assert forecast_service.season_factor([event], "Menswear", in_lead) == (1.0, [])

    def test_the_strongest_event_wins(self, db: Session) -> None:
        eid = _event(db)
        wedding = _event(db, name="Wedding season", demand_factor=1.5, starts_on=date(2026, 11, 1))
        factor, names = forecast_service.season_factor(
            [eid, wedding], "Womenswear stitched", date(2026, 11, 30)
        )
        assert factor == 2.0 and set(names) == {"Eid ul Fitr", "Wedding season"}


@pytest.fixture
def history(db: Session, two_brands, category):  # type: ignore[no-untyped-def]
    """Brand one sold a whole lot to Karachi three weeks ago; brand two sold nothing."""
    (one, one_owner), (two, two_owner) = two_brands
    make_courier(db)
    sold_lot = live_lot(db, one, one_owner, category.id, offset=0)
    order = whole_order(db, make_reseller(db), sold_lot)
    order.status = OrderStatus.PAID
    order.delivery_city = "Karachi"
    order.created_at = NOW - timedelta(weeks=3)
    still = live_lot(db, one, one_owner, category.id, offset=1)
    theirs = live_lot(db, two, two_owner, category.id, offset=2)
    for lot in (still, theirs):
        lot.approved_at = NOW - timedelta(days=40)
    db.commit()
    return {"one": one, "two": two, "still": still, "theirs": theirs, "owner": one_owner}


class TestRun:
    def test_demand_is_forecast_per_city_and_overall(self, db: Session, history) -> None:  # type: ignore[no-untyped-def]
        _event(db)
        forecast_service.run(db, now=NOW)
        rows = db.scalars(select(DemandForecast).where(DemandForecast.city == "Karachi")).all()
        assert len(rows) == forecast_service.FORECAST_WEEKS
        # 100 pieces over eight weeks is 12.5 a week, doubled in the Eid lead up.
        assert {float(r.base_weekly_pieces) for r in rows} == {12.5}
        assert max(float(r.expected_pieces) for r in rows) == 25.0
        overall = db.scalars(
            select(DemandForecast).where(DemandForecast.city == forecast_service.ALL_CITIES)
        ).all()
        assert len(overall) == forecast_service.FORECAST_WEEKS

    def test_slow_lots_are_flagged_with_the_arithmetic(self, db: Session, history) -> None:  # type: ignore[no-untyped-def]
        summary = forecast_service.run(db, now=NOW)
        assert summary.lots_checked == 2
        forecast = db.scalar(select(LotForecast).where(LotForecast.lot_id == history["still"].id))
        assert forecast is not None
        # Its fair share of 12.5 a week across two live lots is 6.25 a week, so
        # its 100 pieces take 16 weeks: on track, not stuck.
        assert float(forecast.weekly_pieces) == 6.25
        assert float(forecast.weeks_to_clear) == 16.0
        assert not forecast.at_risk

    def test_a_category_with_no_sales_is_stuck(
        self,
        db: Session,
        two_brands,
        category,  # type: ignore[no-untyped-def]
    ) -> None:
        (brand, owner), _ = two_brands
        lot = live_lot(db, brand, owner, category.id)
        lot.approved_at = NOW - timedelta(days=45)
        db.commit()
        summary = forecast_service.run(db, now=NOW)
        forecast = db.scalar(select(LotForecast).where(LotForecast.lot_id == lot.id))
        assert summary.lots_flagged == 1
        assert forecast is not None and forecast.at_risk
        assert "45 days" in forecast.reason
        assert summary.warnings == 1


class TestEndpoints:
    def test_a_brand_sees_only_its_own_forecast(
        self,
        client: TestClient,
        db: Session,
        history,
        two_brands,  # type: ignore[no-untyped-def]
    ) -> None:
        forecast_service.run(db, now=NOW)
        db.commit()
        (one, owner), (_, other_owner) = two_brands
        mine = client.get(f"/brands/{one.id}/forecast", headers=auth(owner)).json()
        codes = {item["lot_code"] for item in mine["at_risk"] + mine["on_track"]}
        assert history["theirs"].lot_code not in codes
        assert history["still"].lot_code in codes
        assert (
            client.get(f"/brands/{one.id}/forecast", headers=auth(other_owner)).status_code == 404
        )

    def test_an_admin_corrects_an_event_and_it_is_audited(
        self,
        client: TestClient,
        db: Session,
        admin_user,  # type: ignore[no-untyped-def]
    ) -> None:
        event = _event(db)
        body = {
            "name": "Eid ul Fitr",
            "starts_on": "2026-12-11",
            "ends_on": "2026-12-13",
            "lead_days": 21,
            "demand_factor": 2.0,
            "keywords": ["womenswear"],
        }
        response = client.put(
            f"/admin/season-events/{event.id}", json=body, headers=auth(admin_user)
        )
        assert response.status_code == 200, response.text
        assert response.json()["starts_on"] == "2026-12-11"
        assert db.scalar(select(AuditLog).where(AuditLog.action == "season_event.updated"))

    def test_an_event_cannot_end_before_it_starts(
        self,
        client: TestClient,
        db: Session,
        admin_user,  # type: ignore[no-untyped-def]
    ) -> None:
        body = {
            "name": "Backwards",
            "starts_on": "2026-12-11",
            "ends_on": "2026-12-01",
            "keywords": ["x"],
        }
        response = client.post("/admin/season-events", json=body, headers=auth(admin_user))
        assert response.status_code == 422

    def test_the_job_runs_from_the_admin_endpoint(
        self,
        client: TestClient,
        db: Session,
        history,
        admin_user,  # type: ignore[no-untyped-def]
    ) -> None:
        response = client.post("/admin/jobs/forecast", headers=auth(admin_user))
        assert response.status_code == 200, response.text
        assert response.json()["lots_checked"] == 2
