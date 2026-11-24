# ruff: noqa: S311
# Seeded pseudo random generators on purpose: a failing case must reproduce
# exactly from the seed. Nothing here is security sensitive.
"""Properties of the three money adjacent calculations, over many random cases.

The example tests elsewhere check the cases someone thought of. These check
the rules themselves against thousands of generated ones, with a fixed seed
so a failure reproduces exactly:

- Pool splits: nobody gets more than they asked for, no stock is invented,
  stock that is short is shared out completely and fairly.
- The bargaining floor: whatever the model answers and whatever the buyer
  offers, no counter and no agreement is below the brand's floor or above
  the asking price, and the asking price only ever comes down.
- The markdown floor: whatever reduction the model asks for, including
  negative or absurd numbers, a lot never goes past the brand's floor or its
  advertised band, never goes up, and never moves more than one step.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from math import ceil
from types import SimpleNamespace
from typing import Any

import pytest
from sqlalchemy.orm import Session

from commerce_helpers import live_lot, make_courier, make_reseller, policy_for
from khazana.ai.schemas import BargainReply, MarkdownDecision
from khazana.models import Lot
from khazana.models.enums import NegotiationStatus
from khazana.services import bargaining_service, markdown_service
from khazana.services.order_service import LineChoice
from khazana.services.pool_service import allocate

SEED = 20261123


# --- Pool splits --------------------------------------------------------------


def _random_pool(rng: random.Random):  # type: ignore[no-untyped-def]
    keys = [(size, color) for size in ("S", "M", "L", "XL") for color in ("Red", "Blue")]
    available = {key: rng.randint(0, 40) for key in rng.sample(keys, rng.randint(1, len(keys)))}
    requests = []
    for member in range(rng.randint(1, 6)):
        chosen = rng.sample(keys, rng.randint(1, 4))
        requests.append(
            (
                f"m{member}",
                [LineChoice(size=s, color=c, pieces=rng.randint(1, 50)) for s, c in chosen],
            )
        )
    return available, requests


def test_pool_splits_hold_their_rules_for_random_pools() -> None:
    rng = random.Random(SEED)
    for _ in range(3_000):
        available, requests = _random_pool(rng)
        result = allocate(available, requests)
        assert allocate(available, requests) == result, "the split is deterministic"

        asked: dict[tuple[str, str], dict[str, int]] = {}
        for member, lines in requests:
            for line in lines:
                asked.setdefault((line.size, line.color), {})[member] = line.pieces

        for key, by_member in asked.items():
            stock = available.get(key, 0)
            total = sum(by_member.values())
            given = {
                member: sum(x.pieces for x in result[member] if (x.size, x.color) == key)
                for member in by_member
            }
            assert sum(given.values()) <= stock, "no stock is invented"
            for member, pieces in by_member.items():
                assert 0 <= given[member] <= pieces, "nobody gets more than they asked for"
            if total <= stock:
                assert given == by_member, "when everything fits, everyone gets their ask"
            else:
                assert sum(given.values()) == stock, "short stock is shared out completely"
                for member, pieces in by_member.items():
                    fair = stock * pieces / total
                    assert abs(given[member] - fair) < 1, "each share is within a piece of fair"

        for member, _ in requests:
            assert all(line.pieces >= 1 for line in result[member]), "no empty lines"


# --- The bargaining floor -------------------------------------------------------


def test_the_bargaining_band_never_leaves_the_floor_or_the_asking_price() -> None:
    rng = random.Random(SEED)
    for _ in range(2_000):
        retail = rng.randint(50, 20_000)
        floor_percent = rng.uniform(5, 90)
        floor_price = ceil(retail * (1 - floor_percent / 100))
        list_price = rng.randint(floor_price, retail)
        negotiation = SimpleNamespace(
            floor_price_pkr=floor_price,
            asking_price_pkr=list_price,
            step_pkr=max(1, int(retail * rng.uniform(0.5, 10) / 100)),
        )
        for _round in range(8):
            offer = rng.choice([None, rng.randint(1, retail * 2)])
            band = bargaining_service.round_range(negotiation, offer)  # type: ignore[arg-type]
            assert floor_price <= band.low <= band.high == negotiation.asking_price_pkr
            proposed = rng.randint(-retail, retail * 3)
            counter = bargaining_service.clamp(proposed, band)
            assert band.low <= counter <= band.high
            assert counter >= floor_price
            assert counter <= negotiation.asking_price_pkr, "the asking price only comes down"
            negotiation.asking_price_pkr = counter


@dataclass
class _Reply:
    output: BargainReply


@dataclass
class _RandomBargainer:
    rng: random.Random
    calls: int = 0

    def __call__(self, db: Session, feature: Any, **kwargs: Any) -> _Reply:
        self.calls += 1
        price = self.rng.randint(-1_000, 5_000)
        return _Reply(
            output=BargainReply(
                counter_price_per_piece_pkr=price, message=f"Rs {price}", language="en"
            )
        )


@pytest.fixture
def bargain_lot(db: Session, two_brands, category) -> Lot:  # type: ignore[no-untyped-def]
    (brand, owner), _ = two_brands
    make_courier(db)
    policy = policy_for(db, brand)
    policy.allow_bargaining = True
    policy.bargain_floor_percent = Decimal(75)
    policy.bargain_step_percent = Decimal(3)
    db.commit()
    return live_lot(db, brand, owner, category.id)


def test_random_model_answers_never_take_a_negotiation_below_the_floor(
    db: Session, bargain_lot: Lot, monkeypatch: pytest.MonkeyPatch
) -> None:
    rng = random.Random(SEED)
    monkeypatch.setattr(bargaining_service, "run_feature", _RandomBargainer(rng))
    monkeypatch.setattr(bargaining_service, "rounds_today", lambda *_: 0)
    for buyer_number in range(25):
        buyer = make_reseller(db, phone=f"0301{buyer_number:07d}")
        negotiation = bargaining_service.start(
            db, buyer=buyer, lot_id=bargain_lot.id, message="kam karo", offer=None
        )
        floor_price = negotiation.floor_price_pkr
        asking = negotiation.asking_price_pkr
        for _ in range(bargaining_service.MAX_ROUNDS + 2):
            if negotiation.status != NegotiationStatus.OPEN:
                break
            offer = rng.choice([None, rng.randint(1, asking + 50)])
            bargaining_service.respond(
                db, buyer=buyer, negotiation=negotiation, message="aur kam", offer=offer
            )
            assert floor_price <= negotiation.asking_price_pkr <= asking
            asking = negotiation.asking_price_pkr
        if negotiation.agreed_price_pkr is not None:
            assert negotiation.agreed_price_pkr >= floor_price
        db.rollback()


# --- The markdown floor --------------------------------------------------------


@dataclass
class _Decision:
    output: MarkdownDecision


@dataclass
class _RandomMarker:
    rng: random.Random
    asked: list[float] = field(default_factory=list)

    def __call__(self, db: Session, feature: Any, **kwargs: Any) -> _Decision:
        value = self.rng.choice(
            [self.rng.uniform(-50, 0), self.rng.uniform(0, 10), self.rng.uniform(10, 500)]
        )
        self.asked.append(value)
        # model_construct, so an out of range answer reaches the clamp the way a
        # model that ignored its instructions would deliver it.
        return _Decision(
            output=MarkdownDecision.model_construct(reduce_by_percent=value, reason="Slow.")
        )


def test_random_markdown_answers_never_pass_the_floor_or_the_band(
    db: Session, two_brands, category, monkeypatch: pytest.MonkeyPatch
) -> None:
    rng = random.Random(SEED)
    marker = _RandomMarker(rng)
    monkeypatch.setattr(markdown_service, "run_feature", marker)
    (brand, owner), _ = two_brands
    make_courier(db)
    policy = policy_for(db, brand)
    policy.allow_auto_markdown = True
    policy.markdown_interval_days = 1
    db.commit()
    now = datetime.now(UTC)
    lot = live_lot(db, brand, owner, category.id)
    lot.approved_at = now - timedelta(days=400)
    db.commit()
    retail_total = lot.retail_price_per_piece_pkr * lot.total_pieces

    for case in range(300):
        policy.markdown_step_percent = Decimal(str(round(rng.uniform(0.5, 10), 2)))
        policy.markdown_floor_percent = Decimal(rng.randint(int(lot.discount_percent) + 1, 95))
        policy.max_discount_percent = Decimal(rng.randint(int(lot.discount_percent) + 1, 95))
        ceiling = min(float(policy.markdown_floor_percent), float(policy.max_discount_percent))
        step = float(policy.markdown_step_percent)
        before_price = lot.lot_price_pkr
        before_discount = lot.discount_percent

        markdown_service.mark_down(db, lot=lot, policy=policy, now=now + timedelta(days=case))

        assert lot.lot_price_pkr <= before_price, "a markdown never raises a price"
        assert lot.discount_percent <= ceiling + 1e-9 or lot.lot_price_pkr == before_price
        # One step at most, allowing for rounding to whole rupees per piece.
        per_piece_slack = 100 * lot.total_pieces / retail_total
        assert lot.discount_percent - before_discount <= step + per_piece_slack + 1e-9
        if lot.discount_percent >= ceiling - per_piece_slack:
            lot.lot_price_pkr = before_price  # reset so later cases still have room
        db.flush()
    assert len(marker.asked) > 100, "the property ran against the model, not past it"
