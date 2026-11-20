"""The mixed lot builder: slow stock from several brands, inside a budget.

Each part must be a purchase checkout would accept, so the tests check the
proposal against the brands' own rules as well as against the budget.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from commerce_helpers import (
    auth,
    live_lot,
    make_courier,
    make_reseller,
    open_for_part_orders,
    policy_for,
)
from khazana.models import CartItem, Lot
from khazana.services import mixed_lot_service
from khazana.services.order_service import LineChoice


def _age(db: Session, lot: Lot, days: int) -> None:
    lot.approved_at = datetime.now(UTC) - timedelta(days=days)
    db.commit()


@pytest.fixture
def stock(db: Session, two_brands, category):  # type: ignore[no-untyped-def]
    (one, one_owner), (two, two_owner) = two_brands
    make_courier(db)
    open_for_part_orders(db, one)
    open_for_part_orders(db, two)
    old = live_lot(db, one, one_owner, category.id, offset=0)
    new = live_lot(db, one, one_owner, category.id, offset=1)
    other = live_lot(db, two, two_owner, category.id, offset=2)
    _age(db, old, 60)
    _age(db, new, 2)
    _age(db, other, 30)
    return {"one": one, "two": two, "old": old, "new": new, "other": other}


def test_lines_are_spread_across_sizes() -> None:
    available = [
        LineChoice(size="S", color="black", pieces=2),
        LineChoice(size="M", color="black", pieces=10),
        LineChoice(size="L", color="black", pieces=10),
    ]
    taken = {line.size: line.pieces for line in mixed_lot_service.spread_lines(available, 12)}
    assert taken == {"L": 5, "M": 5, "S": 2}


class TestBuild:
    def test_one_part_per_brand_slowest_stock_first(self, db: Session, stock) -> None:  # type: ignore[no-untyped-def]
        buyer = make_reseller(db)
        proposal = mixed_lot_service.build(
            db, user=buyer, budget_pkr=200_000, target_pieces=60, city="Multan"
        )
        lots = [c.lot.id for c in proposal.components]
        assert proposal.brand_count == 2
        assert stock["old"].id in lots
        assert stock["new"].id not in lots, "one part per brand, and the slower lot wins"
        assert stock["other"].id in lots
        assert proposal.total_pkr <= 200_000
        assert proposal.notes == []

    def test_every_part_respects_its_brands_minimum(self, db: Session, stock) -> None:  # type: ignore[no-untyped-def]
        buyer = make_reseller(db)
        proposal = mixed_lot_service.build(
            db, user=buyer, budget_pkr=200_000, target_pieces=8, city="Multan"
        )
        for component in proposal.components:
            assert component.pieces >= component.lot.min_order_pieces
            assert sum(line.pieces for line in component.lines) == component.pieces

    def test_the_budget_shrinks_the_parts(self, db: Session, stock) -> None:  # type: ignore[no-untyped-def]
        buyer = make_reseller(db)
        proposal = mixed_lot_service.build(
            db, user=buyer, budget_pkr=12_000, target_pieces=100, city="Multan"
        )
        assert proposal.total_pkr <= 12_000
        assert any("within the budget" in note for note in proposal.notes)

    def test_a_brand_that_sells_whole_lots_only_is_skipped(self, db: Session, stock) -> None:  # type: ignore[no-untyped-def]
        policy = policy_for(db, stock["two"])
        policy.allow_part_lot_orders = False
        db.commit()
        buyer = make_reseller(db)
        proposal = mixed_lot_service.build(
            db, user=buyer, budget_pkr=200_000, target_pieces=60, city="Multan"
        )
        assert stock["other"].id not in [c.lot.id for c in proposal.components]
        assert proposal.brand_count == 1
        assert any("not a mixed lot yet" in note for note in proposal.notes)

    def test_bad_input_is_refused(self, db: Session, stock) -> None:  # type: ignore[no-untyped-def]
        with pytest.raises(mixed_lot_service.ValidationFailed):
            mixed_lot_service.build(
                db, user=make_reseller(db), budget_pkr=0, target_pieces=10, city="Multan"
            )


class TestEndpoints:
    def test_propose_then_add_to_cart(
        self,
        client: TestClient,
        db: Session,
        stock,  # type: ignore[no-untyped-def]
    ) -> None:
        buyer = make_reseller(db)
        body = {"budget_pkr": 200_000, "target_pieces": 60}
        proposed = client.post("/catalog/mixed-lots", json=body, headers=auth(buyer))
        assert proposed.status_code == 200, proposed.text
        assert proposed.json()["brand_count"] == 2
        assert db.query(CartItem).count() == 0

        added = client.post("/catalog/mixed-lots/cart", json=body, headers=auth(buyer))
        assert added.status_code == 200, added.text
        assert added.json()["added_to_cart"] is True
        cart = client.get("/cart", headers=auth(buyer)).json()
        assert len(cart["items"]) == 2
        assert all(item["problem"] is None for item in cart["items"])
        assert cart["total_pkr"] == added.json()["total_pkr"]
