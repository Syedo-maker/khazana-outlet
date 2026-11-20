"""The reseller profit helper: arithmetic a buyer can check.

Every expected number here is worked out by hand from the lot, the shipping
rate and the benchmark, so a change to the formula shows up as a wrong number
rather than a vague drift.
"""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from commerce_helpers import auth, live_lot, make_courier, make_reseller
from khazana.core.errors import Conflict, ValidationFailed
from khazana.models import Courier, ResaleBenchmark
from khazana.services import logistics_service, profit_service


@pytest.fixture
def default_benchmark(db: Session) -> ResaleBenchmark:
    row = ResaleBenchmark(
        category_id=None, city=None, low_percent=35, typical_percent=45, high_percent=55
    )
    db.add(row)
    db.commit()
    return row


@pytest.fixture
def lot(db: Session, two_brands, category):  # type: ignore[no-untyped-def]
    (brand, owner), _ = two_brands
    make_courier(db)
    # 100 pieces at Rs 30,000 is Rs 300 a piece against a Rs 1,000 retail price.
    return live_lot(db, brand, owner, category.id)


class TestEstimate:
    def test_the_three_scenarios_from_the_default_benchmark(
        self,
        db: Session,
        lot,
        default_benchmark: ResaleBenchmark,  # type: ignore[no-untyped-def]
    ) -> None:
        shipping = logistics_service.quote(
            db, lot=lot, pieces=100, destination_city="Multan"
        ).cost_pkr
        result = profit_service.estimate(db, lot=lot, city="Multan")

        assert result.goods_pkr == 30_000
        assert result.shipping_pkr == shipping
        assert result.cost_pkr == 30_000 + shipping
        assert [s.price_per_piece_pkr for s in result.scenarios] == [350, 450, 550]
        typical = result.scenarios[1]
        assert typical.revenue_pkr == 45_000
        assert typical.profit_pkr == 45_000 - 30_000 - shipping
        assert result.break_even_pieces == -(-(30_000 + shipping) // 450)
        assert "platform default" in result.benchmark

    def test_the_most_specific_benchmark_wins(
        self,
        db: Session,
        lot,
        default_benchmark: ResaleBenchmark,
        category,  # type: ignore[no-untyped-def]
    ) -> None:
        db.add_all(
            [
                ResaleBenchmark(
                    category_id=category.id,
                    city=None,
                    low_percent=40,
                    typical_percent=50,
                    high_percent=60,
                ),
                ResaleBenchmark(
                    category_id=category.id,
                    city="Multan",
                    low_percent=50,
                    typical_percent=60,
                    high_percent=70,
                ),
            ]
        )
        db.commit()
        multan = profit_service.estimate(db, lot=lot, city="multan")
        lahore = profit_service.estimate(db, lot=lot, city="Lahore")
        assert multan.scenarios[1].price_per_piece_pkr == 600
        assert lahore.scenarios[1].price_per_piece_pkr == 500
        assert "Womenswear stitched in Multan" in multan.benchmark

    def test_the_buyers_own_price_replaces_the_benchmark(
        self,
        db: Session,
        lot,
        default_benchmark: ResaleBenchmark,  # type: ignore[no-untyped-def]
    ) -> None:
        result = profit_service.estimate(
            db, lot=lot, city="Multan", pieces=50, selling_price_pkr=400
        )
        [only] = result.scenarios
        assert only.name == "your price"
        assert result.goods_pkr == 15_000
        assert only.revenue_pkr == 20_000
        assert result.benchmark == "Your own selling price"

    def test_a_loss_is_shown_as_a_loss(
        self,
        db: Session,
        lot,
        default_benchmark: ResaleBenchmark,  # type: ignore[no-untyped-def]
    ) -> None:
        result = profit_service.estimate(db, lot=lot, city="Multan", selling_price_pkr=200)
        assert result.scenarios[0].profit_pkr < 0
        assert result.break_even_pieces is None

    def test_delivery_that_is_not_available_is_said_not_hidden(
        self,
        db: Session,
        lot,
        default_benchmark: ResaleBenchmark,  # type: ignore[no-untyped-def]
    ) -> None:
        for courier in db.scalars(select(Courier)):
            courier.is_active = False
        db.commit()
        result = profit_service.estimate(db, lot=lot, city="Multan")
        assert result.shipping_pkr is None
        assert result.cost_pkr == result.goods_pkr
        assert any("Delivery not included" in a for a in result.assumptions)

    def test_every_estimate_lists_its_assumptions(
        self,
        db: Session,
        lot,
        default_benchmark: ResaleBenchmark,  # type: ignore[no-untyped-def]
    ) -> None:
        result = profit_service.estimate(db, lot=lot, city="Multan")
        text = " ".join(result.assumptions)
        assert "Rs 300 per piece" in text
        assert "retail price of Rs 1,000" in text
        assert "Every piece sells" in text

    @pytest.mark.parametrize(
        ("kwargs", "message"),
        [
            ({"city": ""}, "city"),
            ({"city": "Multan", "pieces": 101}, "between 1 and 100"),
            ({"city": "Multan", "selling_price_pkr": 0}, "at least 1"),
        ],
    )
    def test_bad_input_is_refused(
        self,
        db: Session,
        lot,  # type: ignore[no-untyped-def]
        default_benchmark: ResaleBenchmark,
        kwargs: dict[str, Any],
        message: str,
    ) -> None:
        with pytest.raises(ValidationFailed, match=message):
            profit_service.estimate(db, lot=lot, **kwargs)

    def test_with_no_benchmark_the_admin_is_asked_for_one(self, db: Session, lot) -> None:  # type: ignore[no-untyped-def]
        with pytest.raises(Conflict, match="administrator"):
            profit_service.estimate(db, lot=lot, city="Multan")


class TestEndpoints:
    def test_a_buyer_gets_an_estimate_for_their_city(
        self,
        client: TestClient,
        db: Session,
        lot,
        default_benchmark: ResaleBenchmark,  # type: ignore[no-untyped-def]
    ) -> None:
        buyer = make_reseller(db, city="Multan")
        response = client.get(f"/catalog/{lot.id}/profit", headers=auth(buyer))
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["city"] == "Multan"
        assert [s["name"] for s in body["scenarios"]] == ["low", "typical", "high"]

    def test_an_admin_edits_a_benchmark_and_it_is_audited(
        self,
        client: TestClient,
        db: Session,
        admin_user,
        category,  # type: ignore[no-untyped-def]
    ) -> None:
        body = {
            "category_id": category.id,
            "city": "Karachi",
            "low_percent": 40,
            "typical_percent": 50,
            "high_percent": 65,
        }
        saved = client.put("/admin/resale-benchmarks", json=body, headers=auth(admin_user))
        assert saved.status_code == 200, saved.text
        again = client.put(
            "/admin/resale-benchmarks", json={**body, "high_percent": 70}, headers=auth(admin_user)
        )
        assert again.json()["id"] == saved.json()["id"]
        rows = client.get("/admin/resale-benchmarks", headers=auth(admin_user)).json()
        assert len(rows) == 1 and rows[0]["high_percent"] == 70
        audit = client.get("/admin/audit", headers=auth(admin_user)).json()
        assert any(e["action"] == "resale_benchmark.saved" for e in audit)

    def test_unordered_percentages_are_refused(
        self,
        client: TestClient,
        db: Session,
        admin_user,  # type: ignore[no-untyped-def]
    ) -> None:
        response = client.put(
            "/admin/resale-benchmarks",
            json={"low_percent": 60, "typical_percent": 50, "high_percent": 70},
            headers=auth(admin_user),
        )
        assert response.status_code == 422

    def test_a_buyer_cannot_edit_benchmarks(self, client: TestClient, db: Session) -> None:
        buyer = make_reseller(db)
        response = client.put(
            "/admin/resale-benchmarks",
            json={"low_percent": 10, "typical_percent": 20, "high_percent": 30},
            headers=auth(buyer),
        )
        assert response.status_code == 403
