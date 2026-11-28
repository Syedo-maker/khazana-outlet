"""With no model available, every AI feature falls back to a manual path.

The pilot's AI budget is one dollar a day. When it is spent, or AI is
switched off for a server with no Anthropic key, nothing a person does may
fail: each feature answers with what can be done by hand, spends nothing, and
says why. The bargaining, markdown and logo check fallbacks are tested beside
their features.
"""

from __future__ import annotations

from collections.abc import Iterator
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from catalog_helpers import jpeg_bytes
from commerce_helpers import auth, live_lot, make_courier, make_reseller, policy_for, whole_order
from khazana.ai import availability
from khazana.ai.gateway import cost
from khazana.config import get_settings
from khazana.models.enums import AiFeature, PaymentMethod, SettlementMode
from khazana.services import chat_service, resell_kit_service


@pytest.fixture
def ai_off(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setenv("AI_ENABLED", "false")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture
def seller(db: Session, two_brands):  # type: ignore[no-untyped-def]
    (brand, owner), _ = two_brands
    make_courier(db)
    return brand, owner


@pytest.fixture
def lot(db: Session, seller, category):  # type: ignore[no-untyped-def]
    brand, owner = seller
    return live_lot(db, brand, owner, category.id)


class TestAvailability:
    def test_the_daily_cap_makes_ai_unavailable_for_the_day(
        self, db: Session, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("AI_DAILY_SPEND_LIMIT_USD", "0.10")
        get_settings.cache_clear()
        try:
            assert availability.available_today(db) is True
            cost.record_spend(
                db, feature=AiFeature.PRICING, brand_id=None, cost_usd=Decimal("0.10")
            )
            db.commit()
            assert availability.available_today(db) is False
        finally:
            get_settings.cache_clear()

    def test_the_pilot_cap_is_one_dollar(self) -> None:
        assert get_settings().ai_daily_spend_limit_usd == 1.0

    def test_the_features_endpoint_reports_it(self, client: TestClient, ai_off: None) -> None:
        ai = client.get("/features").json()["ai"]
        assert ai == {"enabled": False, "available_today": False, "daily_cap_usd": 1.0}


@pytest.mark.usefixtures("ai_off")
class TestManualPaths:
    def test_a_price_suggestion_is_the_brands_own_band(
        self, client: TestClient, db: Session, seller, lot
    ) -> None:  # type: ignore[no-untyped-def]
        brand, owner = seller
        policy = policy_for(db, brand)
        response = client.post(f"/ai/lots/{lot.id}/price-suggestion", headers=auth(owner))
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["manual"] is True
        assert body["suggestion"]["suggested_discount_percent_low"] == float(
            policy.min_discount_percent
        )
        assert body["suggestion"]["suggested_discount_percent_high"] == float(
            policy.max_discount_percent
        )
        assert body["cost"] == {"usd": "0", "model": "manual", "from_fixture": False}

    def test_a_risk_score_uses_the_measured_checks_and_asks_a_person(
        self, client: TestClient, seller, lot
    ) -> None:  # type: ignore[no-untyped-def]
        _, owner = seller
        response = client.post(f"/ai/lots/{lot.id}/risk-score", headers=auth(owner))
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["manual"] is True
        assert body["needs_human_review"] is True
        assert body["model_score"] == 0
        assert "measured checks" in body["manual_reason"]

    def test_a_listing_draft_is_left_to_the_brand(
        self, client: TestClient, db: Session, seller, category
    ) -> None:  # type: ignore[no-untyped-def]
        from khazana.models import Category

        db.add(Category(name="Lawn suits", slug="lawn-suits", parent_id=category.id))
        db.commit()
        brand, owner = seller
        response = client.post(
            "/ai/listings/draft",
            data={"brand_id": brand.id},
            files=[("files", ("front.jpg", jpeg_bytes(), "image/jpeg"))],
            headers=auth(owner),
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["draft"] is None
        assert body["manual"] is True
        assert "switched off" in body["manual_reason"]

    def test_a_manifest_points_to_the_import_that_needs_no_ai(
        self, client: TestClient, seller
    ) -> None:  # type: ignore[no-untyped-def]
        brand, owner = seller
        response = client.post(
            "/ai/manifests/extract",
            data={"brand_id": brand.id},
            files={"file": ("lot.csv", b"size,colour,pieces\nM,black,10\n", "text/csv")},
            headers=auth(owner),
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["manual"] is True
        assert body["lines"] == []
        assert "spreadsheet import" in body["summary"]

    def test_the_buyer_assistant_says_what_still_works(
        self, client: TestClient, db: Session
    ) -> None:
        buyer = make_reseller(db)
        response = client.post(
            "/assistant/messages", json={"message": "Lawn suits?"}, headers=auth(buyer)
        )
        assert response.status_code == 200, response.text
        assert response.json()["reply"]["body"] == chat_service.RESTING_REPLY
        ask = client.post("/ai/assistant/ask", json={"message": "Lawn suits?"}, headers=auth(buyer))
        assert ask.status_code == 200
        assert ask.json()["manual"] is True

    def test_the_brand_assistant_too(self, client: TestClient, seller) -> None:  # type: ignore[no-untyped-def]
        brand, owner = seller
        response = client.post(
            f"/brands/{brand.id}/assistant/messages",
            json={"message": "What sold this week?"},
            headers=auth(owner),
        )
        assert response.status_code == 200, response.text
        assert response.json()["reply"]["body"] == chat_service.BRAND_RESTING_REPLY

    def test_a_resell_kit_is_written_from_the_facts(
        self, client: TestClient, db: Session, seller, lot
    ) -> None:  # type: ignore[no-untyped-def]
        brand, _ = seller
        policy = policy_for(db, brand)
        policy.settlement_mode = SettlementMode.DIRECT
        db.commit()
        buyer = make_reseller(db)
        order = whole_order(db, buyer, lot, method=PaymentMethod.COD)
        response = client.post(
            f"/orders/{order.id}/resell-kit", json={"selling_price_pkr": 950}, headers=auth(buyer)
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert lot.title in body["caption_en"]
        assert "950" in body["caption_en"]
        assert body["caption_ur"]
        assert resell_kit_service.template_copy is not None
