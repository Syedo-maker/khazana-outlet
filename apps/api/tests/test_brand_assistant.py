"""The brand assistant: its lookups, and the boundary between brands.

The boundary is the point of these tests. Each lookup is run for one brand
against data that includes another brand's lots and orders, and must return
only its own. A lot code belonging to the other brand must answer exactly as a
code that does not exist.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from commerce_helpers import (
    auth,
    live_lot,
    make_courier,
    make_reseller,
    policy_for,
    whole_order,
)
from khazana.ai.features import brand_assistant
from khazana.ai.schemas import AssistantAnswer, BrandToolCall, BrandToolPlan
from khazana.ai.tools import brand_tools
from khazana.models import Lot, Order
from khazana.models.enums import OrderStatus


def _age(db: Session, lot: Lot, days: int) -> None:
    lot.approved_at = datetime.now(UTC) - timedelta(days=days)
    db.commit()


def _sold(db: Session, order: Order, city: str = "Multan") -> None:
    order.status = OrderStatus.PAID
    order.delivery_city = city
    db.commit()


@pytest.fixture
def market(db: Session, two_brands, category):  # type: ignore[no-untyped-def]
    """Brand one with a slow lot and a sold lot, brand two with its own sale."""
    (one, one_owner), (two, two_owner) = two_brands
    buyer = make_reseller(db)
    make_courier(db)
    slow = live_lot(db, one, one_owner, category.id, offset=0)
    sold = live_lot(db, one, one_owner, category.id, offset=1)
    theirs = live_lot(db, two, two_owner, category.id, offset=2)
    _age(db, slow, 40)
    _age(db, sold, 40)
    _sold(db, whole_order(db, buyer, sold), city="Karachi")
    _sold(db, whole_order(db, buyer, theirs), city="Karachi")
    return {"one": one, "two": two, "slow": slow, "sold": sold, "theirs": theirs}


class TestLookups:
    def test_slow_lots_lists_only_this_brands_unsold_stock(self, db: Session, market) -> None:  # type: ignore[no-untyped-def]
        result = brand_tools.slow_lots(db, brand_id=market["one"].id)
        codes = [row["lot_code"] for row in result["lots"]]
        assert codes[0] == market["slow"].lot_code
        assert market["theirs"].lot_code not in codes
        assert result["lots"][0]["pieces_sold"] == 0
        assert result["lots"][0]["days_live"] >= 39

    def test_a_recently_listed_lot_is_not_called_slow(self, db: Session, market) -> None:  # type: ignore[no-untyped-def]
        _age(db, market["slow"], 3)
        codes = [
            r["lot_code"] for r in brand_tools.slow_lots(db, brand_id=market["one"].id)["lots"]
        ]
        assert market["slow"].lot_code not in codes

    def test_sales_count_only_this_brands_orders(self, db: Session, market) -> None:  # type: ignore[no-untyped-def]
        mine = brand_tools.sales_summary(db, brand_id=market["one"].id, city="Karachi")
        assert mine["orders"] == 1
        assert mine["pieces"] == market["sold"].total_pieces
        assert [row["lot_code"] for row in mine["top_lots"]] == [market["sold"].lot_code]
        assert (
            brand_tools.sales_summary(db, brand_id=market["one"].id, city="Lahore")["orders"] == 0
        )

    def test_an_unpaid_order_is_not_a_sale(self, db: Session, two_brands, category) -> None:  # type: ignore[no-untyped-def]
        (one, owner), _ = two_brands
        lot = live_lot(db, one, owner, category.id)
        make_courier(db)
        whole_order(db, make_reseller(db), lot)
        assert brand_tools.sales_summary(db, brand_id=one.id)["orders"] == 0

    def test_another_brands_lot_answers_as_not_found(self, db: Session, market) -> None:  # type: ignore[no-untyped-def]
        code = market["theirs"].lot_code
        for tool in (brand_tools.lot_performance, brand_tools.discount_room):
            assert tool(db, brand_id=market["one"].id, lot_code=code) == brand_tools.NOT_FOUND
            assert tool(db, brand_id=market["one"].id, lot_code="LOT-NOPE999") == (
                brand_tools.NOT_FOUND
            )

    def test_discount_room_reads_the_brands_own_band(self, db: Session, market) -> None:  # type: ignore[no-untyped-def]
        policy = policy_for(db, market["one"])
        policy.min_discount_percent = Decimal(40)
        policy.max_discount_percent = Decimal(70)
        db.commit()
        lot = market["slow"]
        room = brand_tools.discount_room(db, brand_id=market["one"].id, lot_code=lot.lot_code)
        assert room["band_min_percent"] == 40
        assert room["band_max_percent"] == 70
        assert room["price_per_piece_at_band_max_pkr"] == round(
            lot.retail_price_per_piece_pkr * 0.3
        )

    def test_a_brand_id_in_the_arguments_is_ignored(self, db: Session, market) -> None:  # type: ignore[no-untyped-def]
        """The brand always comes from the session, never from the plan."""
        result = brand_tools.run_tool(
            db,
            "sales_summary",
            {"brand_id": market["two"].id, "city": "Karachi"},
            brand_id=market["one"].id,
        )
        assert [row["lot_code"] for row in result["top_lots"]] == [market["sold"].lot_code]

    def test_the_overview_counts_this_brand_only(self, db: Session, market) -> None:  # type: ignore[no-untyped-def]
        overview = brand_tools.stock_overview(db, brand_id=market["one"].id)
        assert sum(overview["lots_by_status"].values()) == 2

    def test_the_plan_runs_known_tools_for_the_session_brand(self, db: Session, market) -> None:  # type: ignore[no-untyped-def]
        plan = BrandToolPlan(
            calls=[
                BrandToolCall(tool="lot_performance", lot_code=market["theirs"].lot_code),
                BrandToolCall(tool="delete_everything"),
                BrandToolCall(tool="slow_lots"),
            ],
            language="en",
        )
        results, executed, rejected = brand_assistant.execute_plan(
            db, plan, brand_id=market["one"].id
        )
        assert executed == ["lot_performance", "slow_lots"]
        assert rejected == ["delete_everything"]
        assert results["lot_performance#1"] == brand_tools.NOT_FOUND


@dataclass
class _Turn:
    answer: AssistantAnswer
    plan: BrandToolPlan = field(default_factory=lambda: BrandToolPlan(language="en"))
    is_grounded: bool = True
    total_cost_usd: Decimal = Decimal("0.01")


@dataclass
class StubBrandAssistant:
    calls: list[dict[str, Any]] = field(default_factory=list)

    def __call__(self, db: Session, **kwargs: Any) -> _Turn:
        self.calls.append(kwargs)
        return _Turn(answer=AssistantAnswer(answer="Two lots are slow.", language="en"))


@pytest.fixture
def stub(monkeypatch: pytest.MonkeyPatch) -> StubBrandAssistant:
    fake = StubBrandAssistant()
    monkeypatch.setattr(brand_assistant, "ask", fake)
    return fake


class TestEndpoints:
    def test_a_member_asks_about_their_own_brand(
        self,
        client: TestClient,
        db: Session,
        two_brands,
        stub: StubBrandAssistant,  # type: ignore[no-untyped-def]
    ) -> None:
        (one, owner), _ = two_brands
        response = client.post(
            f"/brands/{one.id}/assistant/messages",
            json={"message": "Which of my stock is slow?"},
            headers=auth(owner),
        )
        assert response.status_code == 200, response.text
        assert stub.calls[0]["brand_id"] == one.id
        thread = response.json()["conversation"]["id"]

        listed = client.get(f"/brands/{one.id}/assistant/conversations", headers=auth(owner))
        assert [c["id"] for c in listed.json()] == [thread]

    def test_another_brand_is_not_found(
        self,
        client: TestClient,
        db: Session,
        two_brands,
        stub: StubBrandAssistant,  # type: ignore[no-untyped-def]
    ) -> None:
        (one, _), (_, other_owner) = two_brands
        response = client.post(
            f"/brands/{one.id}/assistant/messages",
            json={"message": "Show me their sales"},
            headers=auth(other_owner),
        )
        assert response.status_code == 404
        assert stub.calls == []

    def test_a_reseller_cannot_use_the_brand_assistant(
        self,
        client: TestClient,
        db: Session,
        two_brands,
        stub: StubBrandAssistant,  # type: ignore[no-untyped-def]
    ) -> None:
        (one, _), _ = two_brands
        buyer = make_reseller(db)
        db.commit()
        response = client.post(
            f"/brands/{one.id}/assistant/messages", json={"message": "hi"}, headers=auth(buyer)
        )
        assert response.status_code == 403
        assert stub.calls == []

    def test_a_brand_thread_stays_in_its_brand(
        self,
        client: TestClient,
        db: Session,
        two_brands,
        stub: StubBrandAssistant,  # type: ignore[no-untyped-def]
    ) -> None:
        (one, owner), _ = two_brands
        thread = client.post(
            f"/brands/{one.id}/assistant/messages",
            json={"message": "slow stock?"},
            headers=auth(owner),
        ).json()["conversation"]["id"]

        # Not readable or continuable through the buyer assistant.
        assert (
            client.get(f"/assistant/conversations/{thread}", headers=auth(owner)).status_code == 404
        )
        assert client.get("/assistant/conversations", headers=auth(owner)).json() == []
        continued = client.post(
            "/assistant/messages",
            json={"message": "and lawn?", "conversation_id": thread},
            headers=auth(owner),
        )
        assert continued.status_code == 404
