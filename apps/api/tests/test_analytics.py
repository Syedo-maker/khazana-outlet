"""Reports: brand sales, platform growth, AI cost per unit, and impact.

The lot used: retail Rs 1,000 a piece, 100 pieces for Rs 30,000, so Rs 300 a
piece at 70 percent off, in "Womenswear stitched".
"""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from commerce_helpers import auth, live_lot, make_courier, make_reseller, whole_order
from khazana.models import AiJob, AiOutput, ImpactFactor, Partner, Redirection, utcnow
from khazana.models.enums import AiFeature, AiJobStatus, OrderStatus, RedirectStatus
from khazana.services import analytics_service


@pytest.fixture
def sale(db: Session, two_brands, category):  # type: ignore[no-untyped-def]
    (one, owner), _ = two_brands
    make_courier(db)
    lot = live_lot(db, one, owner, category.id)
    order = whole_order(db, make_reseller(db), lot)
    order.status = OrderStatus.PAID
    order.delivery_city = "Karachi"
    db.commit()
    return {"brand": one, "owner": owner, "lot": lot, "order": order}


def _ai(db: Session, feature: AiFeature, cost: str, calls: int = 1) -> None:
    for _ in range(calls):
        job = AiJob(feature=feature, status=AiJobStatus.SUCCEEDED)
        db.add(job)
        db.flush()
        db.add(
            AiOutput(
                job_id=job.id,
                model="claude-opus-5-5",
                prompt_name=feature.value,
                prompt_version=1,
                cost_usd=Decimal(cost),
                input_tokens=1000,
                output_tokens=200,
            )
        )
    db.commit()


class TestBrandReport:
    def test_sales_by_city_category_and_price(self, db: Session, sale) -> None:  # type: ignore[no-untyped-def]
        report = analytics_service.brand_report(db, brand_id=sale["brand"].id)
        assert report["orders"] == 1
        assert report["pieces"] == 100
        assert report["goods_pkr"] == 30_000
        assert report["average_price_per_piece_pkr"] == 300
        assert report["average_discount_percent"] == 70.0
        assert report["by_city"] == [{"city": "Karachi", "pieces": 100}]
        assert report["by_category"] == [{"category": "Womenswear stitched", "pieces": 100}]

    def test_another_brands_sales_are_not_counted(
        self,
        db: Session,
        sale,
        two_brands,  # type: ignore[no-untyped-def]
    ) -> None:
        _, (two, _) = two_brands
        assert analytics_service.brand_report(db, brand_id=two.id)["orders"] == 0


class TestPlatformReport:
    def test_growth_against_the_period_before(self, db: Session, sale) -> None:  # type: ignore[no-untyped-def]
        report = analytics_service.platform_report(db, days=30)
        assert report["gmv_pkr"] == 30_000
        assert report["orders"] == 1
        assert report["active_buyers"] == 1
        assert report["commission_pkr"] == sale["order"].commission_pkr
        assert report["change_percent"]["gmv"] is None, "nothing to compare with"

        sale["order"].created_at = utcnow() - timedelta(days=40)
        db.commit()
        later = analytics_service.platform_report(db, days=30)
        assert later["gmv_pkr"] == 0
        assert later["change_percent"]["gmv"] == -100.0


class TestAiCosts:
    def test_cost_per_feature_per_listing_and_per_order(
        self,
        db: Session,
        sale,  # type: ignore[no-untyped-def]
    ) -> None:
        _ai(db, AiFeature.LISTING_FROM_PHOTOS, "0.0300")
        _ai(db, AiFeature.PRICING, "0.0100", calls=2)
        _ai(db, AiFeature.ASSISTANT_BUYER, "0.0050", calls=4)
        _ai(db, AiFeature.ASSISTANT_BRAND, "0.0200")
        report = analytics_service.ai_costs(db, days=30)
        assert report["total_usd"] == "0.0900"
        first = report["features"][0]
        assert first["feature"] == "listing_from_photos" and first["calls"] == 1
        # One lot created: 0.03 + 0.02 of listing features.
        assert report["cost_per_listing_usd"] == "0.0500"
        # One sold order: 0.02 of buyer features. The brand assistant is in neither.
        assert report["cost_per_order_usd"] == "0.0200"

    def test_no_orders_means_no_unit_cost(self, db: Session) -> None:
        _ai(db, AiFeature.ASSISTANT_BUYER, "0.0100")
        report = analytics_service.ai_costs(db, days=30)
        assert report["cost_per_order_usd"] is None


class TestImpact:
    def test_sold_and_second_life_pieces_with_the_factor_used(
        self,
        db: Session,
        sale,
        two_brands,
        category,  # type: ignore[no-untyped-def]
    ) -> None:
        db.add(
            ImpactFactor(
                keyword="*", kg_per_piece=0.5, water_litres_per_kg=10_000, co2_kg_per_kg=15
            )
        )
        partner = Partner(
            name="NGO",
            kind="ngo",
            city="Lahore",
            categories={"words": []},
            grades={"grades": []},
        )
        db.add(partner)
        db.flush()
        db.add(
            Redirection(
                lot_id=sale["lot"].id,
                brand_id=sale["brand"].id,
                partner_id=partner.id,
                route="donation",
                pieces=40,
                status=RedirectStatus.COLLECTED,
                collected_at=utcnow(),
            )
        )
        db.commit()
        report = analytics_service.impact_report(db, brand_id=sale["brand"].id)
        assert report["sold"] == {
            "pieces": 100,
            "kg": 50.0,
            "water_litres": 500_000,
            "co2_kg": 750.0,
        }
        assert report["second_life"]["pieces"] == 40
        assert report["second_life"]["kg"] == 20.0
        assert [f["keyword"] for f in report["factors"]] == ["*"]
        assert "estimates" in report["assumption"]


class TestEndpoints:
    def test_brand_reports_are_scoped_and_admin_reports_are_admin_only(
        self,
        client: TestClient,
        db: Session,
        sale,
        two_brands,
        admin_user,  # type: ignore[no-untyped-def]
    ) -> None:
        (one, owner), (_, other_owner) = two_brands
        assert client.get(f"/brands/{one.id}/analytics", headers=auth(owner)).status_code == 200
        assert client.get(f"/brands/{one.id}/impact", headers=auth(owner)).status_code == 200
        assert (
            client.get(f"/brands/{one.id}/analytics", headers=auth(other_owner)).status_code == 404
        )
        assert client.get("/admin/ai-costs", headers=auth(owner)).status_code == 403
        costs = client.get("/admin/ai-costs", headers=auth(admin_user))
        assert costs.status_code == 200
        assert client.get("/admin/analytics", headers=auth(admin_user)).json()["orders"] == 1
