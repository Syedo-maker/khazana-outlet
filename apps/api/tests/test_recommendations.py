"""Lot recommendations: what ranks first, and why.

The ranking is deterministic, so these tests can say exactly which lot should
come first for a given buyer and check the reason given for it.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from commerce_helpers import auth, live_lot, make_courier, make_reseller, whole_order
from khazana.models import Category, SavedSearch
from khazana.models.enums import OrderStatus, UserRole
from khazana.services import recommendation_service
from khazana.services.search_service import Viewer


def _viewer(city: str) -> Viewer:
    return Viewer(role=UserRole.RESELLER, verified=True, city=city)


@pytest.fixture
def menswear(db: Session) -> Category:
    row = Category(name="Menswear", slug="menswear")
    db.add(row)
    db.commit()
    return row


class TestColdStart:
    def test_a_new_buyer_sees_stock_in_their_own_city_first(
        self,
        db: Session,
        two_brands,
        category,  # type: ignore[no-untyped-def]
    ) -> None:
        (brand, owner), _ = two_brands
        far = live_lot(db, brand, owner, category.id, offset=0, stock_city="Karachi")
        near = live_lot(db, brand, owner, category.id, offset=1, stock_city="Multan")
        buyer = make_reseller(db, city="Multan")

        ranked = recommendation_service.recommend(db, user_id=buyer.id, viewer=_viewer("Multan"))
        assert [rec.lot.id for rec in ranked][:2] == [near.id, far.id]
        assert "Stock is in Multan, your city" in ranked[0].reasons
        assert {"code": "in_your_city", "city": "Multan"} in ranked[0].reason_codes


class TestHistory:
    def test_a_category_the_buyer_bought_ranks_first(
        self,
        db: Session,
        two_brands,
        category,
        menswear,  # type: ignore[no-untyped-def]
    ) -> None:
        (brand, owner), _ = two_brands
        make_courier(db)
        bought = live_lot(db, brand, owner, category.id, offset=0)
        buyer = make_reseller(db)
        order = whole_order(db, buyer, bought)
        order.status = OrderStatus.PAID
        db.commit()

        other = live_lot(db, brand, owner, menswear.id, offset=1, lot_price_pkr=25_000)
        same = live_lot(db, brand, owner, category.id, offset=2)

        ranked = recommendation_service.recommend(db, user_id=buyer.id, viewer=_viewer("Multan"))
        ids = [rec.lot.id for rec in ranked]
        assert bought.id not in ids, "a lot already bought is not recommended again"
        assert ids.index(same.id) < ids.index(other.id)
        assert "You have bought Womenswear stitched before" in ranked[0].reasons
        assert "Priced close to what you usually pay" in ranked[0].reasons

    def test_a_saved_search_category_counts_as_interest(
        self,
        db: Session,
        two_brands,
        category,
        menswear,  # type: ignore[no-untyped-def]
    ) -> None:
        (brand, owner), _ = two_brands
        live_lot(db, brand, owner, category.id, offset=0)
        wanted = live_lot(db, brand, owner, menswear.id, offset=1)
        buyer = make_reseller(db)
        db.add(SavedSearch(user_id=buyer.id, name="Men", filters={"category_id": menswear.id}))
        db.commit()

        ranked = recommendation_service.recommend(db, user_id=buyer.id, viewer=_viewer("Multan"))
        assert ranked[0].lot.id == wanted.id
        assert "Matches a saved search for Menswear" in ranked[0].reasons


class TestVisibility:
    def test_only_lots_the_buyer_may_open_are_recommended(
        self,
        db: Session,
        two_brands,
        category,  # type: ignore[no-untyped-def]
    ) -> None:
        from catalog_helpers import build_submitted_lot

        (brand, owner), _ = two_brands
        visible = live_lot(db, brand, owner, category.id, offset=0)
        pending = build_submitted_lot(db, brand, owner, category.id, offset=1)
        buyer = make_reseller(db)

        ids = {
            rec.lot.id
            for rec in recommendation_service.recommend(
                db, user_id=buyer.id, viewer=_viewer("Multan")
            )
        }
        assert visible.id in ids
        assert pending.id not in ids


class TestEndpoint:
    def test_recommendations_come_with_reasons(
        self,
        client: TestClient,
        db: Session,
        two_brands,
        category,  # type: ignore[no-untyped-def]
    ) -> None:
        (brand, owner), _ = two_brands
        live_lot(db, brand, owner, category.id, stock_city="Multan")
        buyer = make_reseller(db, city="Multan")

        response = client.get("/catalog/recommendations", headers=auth(buyer))
        assert response.status_code == 200, response.text
        [item] = response.json()
        assert item["reasons"]
        assert item["score"] > 0

    def test_an_anonymous_caller_is_refused(self, client: TestClient) -> None:
        assert client.get("/catalog/recommendations").status_code == 401
