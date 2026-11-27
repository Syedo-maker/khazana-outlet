"""The bargaining bot against ADR 0001's four conditions.

The lot: retail Rs 1,000 a piece, listed at Rs 300 a piece (100 pieces for
Rs 30,000). The brand's bargaining floor is 75 percent off, so Rs 250, and its
step is 3 percent of retail, so Rs 30. Round one may therefore offer from
Rs 270 to Rs 300.

The model is a stub that answers whatever price the test tells it to, which
is how a misbehaving model is simulated: the clamp has to hold regardless.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from commerce_helpers import DELIVERY_JSON, auth, live_lot, make_courier, make_reseller, policy_for
from khazana.ai.schemas import BargainReply
from khazana.core.errors import Conflict
from khazana.models import AuditLog, Lot, Negotiation, Order
from khazana.models.enums import NegotiationStatus, PaymentMethod
from khazana.services import bargaining_service
from khazana.services.order_service import Delivery


@dataclass
class _Result:
    output: BargainReply


@dataclass
class StubModel:
    price: int = 290
    message: str = "For 100 pieces I can do Rs 290 per piece."
    calls: list[dict[str, Any]] = field(default_factory=list)

    def __call__(self, db: Session, feature: Any, **kwargs: Any) -> _Result:
        self.calls.append(kwargs)
        return _Result(
            output=BargainReply(
                counter_price_per_piece_pkr=self.price, message=self.message, language="en"
            )
        )


@pytest.fixture
def model(monkeypatch: pytest.MonkeyPatch) -> StubModel:
    stub = StubModel()
    monkeypatch.setattr(bargaining_service, "run_feature", stub)
    return stub


@pytest.fixture
def lot(db: Session, two_brands, category) -> Lot:  # type: ignore[no-untyped-def]
    (brand, owner), _ = two_brands
    make_courier(db)
    policy = policy_for(db, brand)
    policy.allow_bargaining = True
    policy.bargain_floor_percent = Decimal(75)
    policy.bargain_step_percent = Decimal(3)
    db.commit()
    return live_lot(db, brand, owner, category.id)


@pytest.fixture
def buyer(db: Session):  # type: ignore[no-untyped-def]
    return make_reseller(db)


def _start(db: Session, buyer, lot: Lot, offer: int | None = 200) -> Negotiation:  # type: ignore[no-untyped-def]
    return bargaining_service.start(
        db, buyer=buyer, lot_id=lot.id, message="200 kar do", offer=offer
    )


class TestOffByDefault:
    def test_a_brand_that_has_not_turned_it_on_has_fixed_prices(
        self,
        db: Session,
        two_brands,
        category,
        buyer,
        model,  # type: ignore[no-untyped-def]
    ) -> None:
        (brand, owner), _ = two_brands
        make_courier(db)
        plain = live_lot(db, brand, owner, category.id)
        with pytest.raises(Conflict, match="fixed"):
            _start(db, buyer, plain)
        assert model.calls == []

    def test_a_lot_can_refuse_even_when_the_brand_allows_it(
        self,
        db: Session,
        lot: Lot,
        buyer,
        model,  # type: ignore[no-untyped-def]
    ) -> None:
        lot.bargaining_enabled = False
        db.commit()
        with pytest.raises(Conflict, match="fixed"):
            _start(db, buyer, lot)

    def test_no_floor_means_no_room(self, db: Session, lot: Lot, buyer, model) -> None:  # type: ignore[no-untyped-def]
        policy_for(db, lot.brand).bargain_floor_percent = None
        db.commit()
        with pytest.raises(Conflict, match="fixed"):
            _start(db, buyer, lot)


class TestTheClamp:
    def test_a_counter_below_the_band_is_raised_to_it(
        self,
        db: Session,
        lot: Lot,
        buyer,
        model: StubModel,  # type: ignore[no-untyped-def]
    ) -> None:
        model.price = 100
        model.message = "Fine, Rs 100 per piece."
        negotiation = _start(db, buyer, lot)
        assert negotiation.asking_price_pkr == 270
        last = negotiation.messages[-1]
        assert last.clamped is True and last.proposed_pkr == 100
        assert "100" not in last.body, "the buyer is not shown the price the clamp refused"

    def test_a_counter_above_the_asking_price_is_lowered_to_it(
        self,
        db: Session,
        lot: Lot,
        buyer,
        model: StubModel,  # type: ignore[no-untyped-def]
    ) -> None:
        model.price = 500
        negotiation = _start(db, buyer, lot)
        assert negotiation.asking_price_pkr == 300

    def test_the_price_never_goes_below_the_floor_however_long_it_runs(
        self,
        db: Session,
        lot: Lot,
        buyer,
        model: StubModel,  # type: ignore[no-untyped-def]
    ) -> None:
        model.price = 1
        negotiation = _start(db, buyer, lot, offer=None)
        for _ in range(8):
            if negotiation.status != NegotiationStatus.OPEN:
                break
            bargaining_service.respond(
                db, buyer=buyer, negotiation=negotiation, message="less", offer=None
            )
        assert negotiation.asking_price_pkr >= negotiation.floor_price_pkr == 250

    def test_every_counter_is_audited(
        self,
        db: Session,
        lot: Lot,
        buyer,
        model: StubModel,  # type: ignore[no-untyped-def]
    ) -> None:
        negotiation = _start(db, buyer, lot)
        entries = db.scalars(select(AuditLog).where(AuditLog.entity_id == negotiation.id)).all()
        assert [e.action for e in entries] == ["negotiation.counter"]
        assert entries[0].actor_kind == "ai"
        assert entries[0].before == {"asking_price_pkr": 300}
        assert entries[0].after["asking_price_pkr"] == 290


class TestWhatTheModelSees:
    def test_the_floor_is_never_sent_to_the_model(
        self,
        db: Session,
        lot: Lot,
        buyer,
        model: StubModel,  # type: ignore[no-untyped-def]
    ) -> None:
        _start(db, buyer, lot)
        values = model.calls[0]["prompt_values"]
        assert values["allowed_low_pkr"] == 270
        assert values["allowed_high_pkr"] == 300
        assert "250" not in json.dumps(values)


class TestAgreement:
    def test_an_offer_inside_the_round_is_accepted(
        self,
        db: Session,
        lot: Lot,
        buyer,
        model: StubModel,  # type: ignore[no-untyped-def]
    ) -> None:
        negotiation = _start(db, buyer, lot, offer=280)
        assert negotiation.status == NegotiationStatus.AGREED
        assert negotiation.agreed_price_pkr == 280
        assert model.calls == [], "accepting a fair offer needs no model call"

    def test_an_offer_below_the_floor_is_never_accepted(
        self,
        db: Session,
        lot: Lot,
        buyer,
        model: StubModel,  # type: ignore[no-untyped-def]
    ) -> None:
        negotiation = _start(db, buyer, lot, offer=240)
        assert negotiation.status == NegotiationStatus.OPEN
        assert negotiation.asking_price_pkr >= 250

    def test_ordering_at_the_agreed_price(
        self,
        db: Session,
        lot: Lot,
        buyer,
        model: StubModel,  # type: ignore[no-untyped-def]
    ) -> None:
        negotiation = _start(db, buyer, lot)
        bargaining_service.accept(db, buyer=buyer, negotiation_id=negotiation.id)
        order = bargaining_service.order(
            db,
            buyer=buyer,
            negotiation_id=negotiation.id,
            delivery=Delivery(city="Multan", address="Shop 12, Hussain Agahi", phone="03001234567"),
            method=PaymentMethod.JAZZCASH,
        )
        assert order.unit_price_pkr == 290
        assert order.subtotal_pkr == 290 * 100
        assert negotiation.status == NegotiationStatus.ORDERED

    def test_the_hold_expires(self, db: Session, lot: Lot, buyer, model: StubModel) -> None:  # type: ignore[no-untyped-def]
        negotiation = _start(db, buyer, lot, offer=280)
        negotiation.agreed_until = datetime.now(UTC) - timedelta(minutes=1)
        db.commit()
        with pytest.raises(Conflict, match="48 hour"):
            bargaining_service.order(
                db,
                buyer=buyer,
                negotiation_id=negotiation.id,
                delivery=Delivery(city="Multan", address="Shop 12, Agahi", phone="03001234567"),
                method=PaymentMethod.JAZZCASH,
            )
        assert db.query(Order).count() == 0

    def test_a_brand_that_turns_it_off_closes_open_negotiations(
        self,
        db: Session,
        lot: Lot,
        buyer,
        model: StubModel,  # type: ignore[no-untyped-def]
    ) -> None:
        negotiation = _start(db, buyer, lot, offer=None)
        calls = len(model.calls)
        lot.bargaining_enabled = False
        db.commit()
        bargaining_service.respond(
            db, buyer=buyer, negotiation=negotiation, message="ok?", offer=None
        )
        db.commit()
        db.expire_all()
        assert db.get(Negotiation, negotiation.id).status == NegotiationStatus.WITHDRAWN
        assert "closed this lot" in negotiation.messages[-1].body
        assert len(model.calls) == calls, "a closed negotiation makes no model call"

    def test_an_expired_hold_does_not_block_a_new_negotiation(
        self,
        db: Session,
        lot: Lot,
        buyer,
        model: StubModel,  # type: ignore[no-untyped-def]
    ) -> None:
        first = _start(db, buyer, lot, offer=280)
        first.agreed_until = datetime.now(UTC) - timedelta(minutes=1)
        db.commit()
        second = _start(db, buyer, lot, offer=None)
        assert second.id != first.id
        assert first.status == NegotiationStatus.EXPIRED


class TestDailyLimit:
    def test_rounds_count_against_the_daily_limit(
        self,
        db: Session,
        lot: Lot,
        buyer,
        model: StubModel,
        monkeypatch: pytest.MonkeyPatch,  # type: ignore[no-untyped-def]
    ) -> None:
        from khazana.config import get_settings
        from khazana.core.errors import RateLimited

        monkeypatch.setattr(get_settings(), "assistant_daily_message_limit", 2)
        negotiation = _start(db, buyer, lot, offer=None)
        bargaining_service.respond(
            db, buyer=buyer, negotiation=negotiation, message="less", offer=None
        )
        calls = len(model.calls)
        with pytest.raises(RateLimited, match="midnight Pakistan time"):
            bargaining_service.respond(
                db, buyer=buyer, negotiation=negotiation, message="less", offer=None
            )
        assert len(model.calls) == calls, "a refused round costs nothing"

    def test_assistant_messages_and_rounds_share_one_limit(
        self,
        db: Session,
        lot: Lot,
        buyer,
        model: StubModel,
        monkeypatch: pytest.MonkeyPatch,  # type: ignore[no-untyped-def]
    ) -> None:
        from khazana.config import get_settings
        from khazana.core.errors import RateLimited
        from khazana.models import AssistantConversation, AssistantMessage
        from khazana.models.enums import ChatRole

        monkeypatch.setattr(get_settings(), "assistant_daily_message_limit", 2)
        negotiation = _start(db, buyer, lot, offer=None)
        thread = AssistantConversation(user_id=buyer.id, title="hi")
        db.add(thread)
        db.flush()
        db.add(
            AssistantMessage(
                conversation_id=thread.id,
                user_id=buyer.id,
                role=ChatRole.BUYER,
                body="hi",
                tools_used={},
            )
        )
        db.commit()
        with pytest.raises(RateLimited):
            bargaining_service.respond(
                db, buyer=buyer, negotiation=negotiation, message="less", offer=None
            )


class TestEndpoints:
    def test_the_buyer_never_sees_the_floor_and_the_brand_does(
        self,
        client: TestClient,
        db: Session,
        lot: Lot,
        buyer,
        two_brands,
        model,  # type: ignore[no-untyped-def]
    ) -> None:
        (brand, owner), _ = two_brands
        started = client.post(
            "/negotiations",
            json={"lot_id": lot.id, "message": "200?", "offer_pkr": 200},
            headers=auth(buyer),
        )
        assert started.status_code == 201, started.text
        body = started.json()
        assert "floor_price_pkr" not in body and "step_pkr" not in body
        assert "250" not in json.dumps(body)

        brand_view = client.get(f"/brands/{brand.id}/negotiations", headers=auth(owner)).json()
        assert brand_view[0]["floor_price_pkr"] == 250

    def test_another_buyer_and_another_brand_get_404(
        self,
        client: TestClient,
        db: Session,
        lot: Lot,
        buyer,
        two_brands,
        model,  # type: ignore[no-untyped-def]
    ) -> None:
        (brand, _), (_, other_owner) = two_brands
        negotiation = _start(db, buyer, lot)
        db.commit()
        stranger = make_reseller(db, phone="03008888888")
        assert (
            client.get(f"/negotiations/{negotiation.id}", headers=auth(stranger)).status_code == 404
        )
        assert (
            client.get(f"/brands/{brand.id}/negotiations", headers=auth(other_owner)).status_code
            == 404
        )

    def test_the_brand_switches_a_lot_and_null_inherits(
        self,
        client: TestClient,
        db: Session,
        lot: Lot,
        two_brands,  # type: ignore[no-untyped-def]
    ) -> None:
        (_, owner), _ = two_brands
        off = client.patch(
            f"/lots/{lot.id}/agents", json={"bargaining_enabled": False}, headers=auth(owner)
        )
        assert off.json()["bargaining_enabled"] is False
        back = client.patch(
            f"/lots/{lot.id}/agents", json={"bargaining_enabled": None}, headers=auth(owner)
        )
        assert back.json()["bargaining_enabled"] is None
        actions = [
            e.action for e in db.scalars(select(AuditLog).where(AuditLog.entity_id == lot.id))
        ]
        assert actions.count("lot.agents_changed") == 2

    def test_order_endpoint(
        self,
        client: TestClient,
        db: Session,
        lot: Lot,
        buyer,
        model,  # type: ignore[no-untyped-def]
    ) -> None:
        negotiation = _start(db, buyer, lot, offer=280)
        db.commit()
        response = client.post(
            f"/negotiations/{negotiation.id}/order",
            json={
                "delivery_address": DELIVERY_JSON["delivery_address"],
                "delivery_phone": DELIVERY_JSON["delivery_phone"],
                "payment_method": "jazzcash",
            },
            headers=auth(buyer),
        )
        assert response.status_code == 200, response.text
        assert response.json()["status"] == "ordered"


class TestWithoutAModel:
    def test_the_daily_cap_gives_the_brands_own_step_not_an_error(
        self, db: Session, lot: Lot, buyer, monkeypatch: pytest.MonkeyPatch
    ) -> None:  # type: ignore[no-untyped-def]
        """No model today: code comes down by the brand's step, inside the
        band the clamp already allows, and the move is audited as the system's."""
        from khazana.core.errors import SpendLimitReached

        def capped(*args: Any, **kwargs: Any) -> Any:
            raise SpendLimitReached("cap")

        monkeypatch.setattr(bargaining_service, "run_feature", capped)
        negotiation = _start(db, buyer, lot)
        band = bargaining_service.round_range(negotiation, None)
        assert negotiation.status == NegotiationStatus.OPEN
        assert (
            negotiation.floor_price_pkr
            <= negotiation.asking_price_pkr
            <= negotiation.list_price_pkr
        )
        assert negotiation.asking_price_pkr >= band.low
        assert "per piece" in negotiation.messages[-1].body
        entry = db.scalar(select(AuditLog).where(AuditLog.action == "negotiation.counter"))
        assert entry is not None and entry.actor_kind == "system"
