"""Committee pools: joining, splitting by need, and placing together.

The lot in these tests has 100 pieces, 25 each of S blue, M blue, L red and
XL red, a minimum order of 10 pieces and Rs 300 a piece. The brand's minimum
order value is raised to Rs 15,000 (50 pieces) so that no single member here
could buy alone, which is the situation pools exist for.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from commerce_helpers import auth, live_lot, make_courier, make_reseller, policy_for
from khazana.core.errors import Conflict, Forbidden
from khazana.models import Order, Pool
from khazana.models.enums import OrderStatus, PaymentMethod, PoolStatus
from khazana.services import pool_service
from khazana.services.order_service import LineChoice


def _lines(**sizes: int) -> list[dict[str, Any]]:
    colours = {"S": "blue", "M": "blue", "L": "red", "XL": "red"}
    return [{"size": s, "color": colours[s], "pieces": n} for s, n in sizes.items()]


def _member(db: Session, phone: str, city: str = "Multan"):  # type: ignore[no-untyped-def]
    return make_reseller(db, phone=phone, city=city)


@pytest.fixture
def lot(db: Session, two_brands, category):  # type: ignore[no-untyped-def]
    (brand, owner), _ = two_brands
    make_courier(db)
    policy = policy_for(db, brand)
    policy.allow_pooled_orders = True
    policy.min_lot_value_pkr = 15_000
    db.commit()
    return live_lot(db, brand, owner, category.id)


def _open(db: Session, lot, user, **sizes: int) -> Pool:  # type: ignore[no-untyped-def]
    return pool_service.open_pool(
        db,
        organiser=user,
        lot_id=lot.id,
        lines=_lines(**sizes),
        address="Shop 3, Hussain Agahi",
        phone="03001234567",
        method=PaymentMethod.JAZZCASH,
    )


def _join(db: Session, pool: Pool, user, **sizes: int) -> Pool:  # type: ignore[no-untyped-def]
    return pool_service.join(
        db,
        user=user,
        pool_id=pool.id,
        lines=_lines(**sizes),
        address="Shop 9, Ghanta Ghar",
        phone="03007654321",
        method=PaymentMethod.JAZZCASH,
    )


class TestAllocation:
    def test_requests_that_fit_are_met_in_full(self) -> None:
        stock = {("S", "blue"): 25}
        got = pool_service.allocate(
            stock,
            [("a", [LineChoice("S", "blue", 10)]), ("b", [LineChoice("S", "blue", 15)])],
        )
        assert got["a"][0].pieces == 10 and got["b"][0].pieces == 15

    def test_scarce_stock_is_shared_in_proportion_to_need(self) -> None:
        stock = {("S", "blue"): 25}
        got = pool_service.allocate(
            stock,
            [
                ("a", [LineChoice("S", "blue", 30)]),
                ("b", [LineChoice("S", "blue", 15)]),
                ("c", [LineChoice("S", "blue", 5)]),
            ],
        )
        pieces = {member: lines[0].pieces for member, lines in got.items()}
        assert pieces == {"a": 15, "b": 8, "c": 2}
        assert sum(pieces.values()) == 25


class TestMembership:
    def test_a_brand_must_allow_pools(self, db: Session, lot) -> None:  # type: ignore[no-untyped-def]
        policy_for(db, lot.brand).allow_pooled_orders = False
        db.commit()
        with pytest.raises(Conflict, match="does not allow pooled"):
            _open(db, lot, _member(db, "03001000001"), S=10)

    def test_only_resellers_in_the_pools_city_may_join(self, db: Session, lot) -> None:  # type: ignore[no-untyped-def]
        pool = _open(db, lot, _member(db, "03001000001"), S=10)
        with pytest.raises(Forbidden, match="Multan"):
            _join(db, pool, _member(db, "03001000002", city="Karachi"), M=10)

    def test_a_pool_fills_up(self, db: Session, lot) -> None:  # type: ignore[no-untyped-def]
        pool = _open(db, lot, _member(db, "03001000001"), S=5)
        for n in range(2, 5):
            _join(db, pool, _member(db, f"0300100000{n}"), M=5)
        with pytest.raises(Conflict, match="full"):
            _join(db, pool, _member(db, "03001000009"), L=5)

    def test_when_the_organiser_leaves_the_next_member_organises(self, db: Session, lot) -> None:  # type: ignore[no-untyped-def]
        first = _member(db, "03001000001")
        second = _member(db, "03001000002")
        pool = _open(db, lot, first, S=5)
        _join(db, pool, second, M=5)
        pool_service.leave(db, user=first, pool_id=pool.id)
        assert pool.organiser_user_id == second.id
        pool_service.leave(db, user=second, pool_id=pool.id)
        assert pool.status == PoolStatus.CANCELLED


class TestPlacing:
    def test_three_members_who_could_not_buy_alone_buy_together(self, db: Session, lot) -> None:  # type: ignore[no-untyped-def]
        members = [_member(db, f"0300100000{n}") for n in range(1, 4)]
        pool = _open(db, lot, members[0], S=20)
        _join(db, pool, members[1], M=20, S=10)
        _join(db, pool, members[2], L=15)

        orders = pool_service.place(db, actor=members[0], pool_id=pool.id)
        db.commit()

        assert pool.status == PoolStatus.ORDERED
        assert len(orders) == 3
        by_buyer = {o.buyer_user_id: o for o in orders}
        # 30 S blue asked for, 25 in stock: shared 2 to 1 by need.
        first = {(x.size, x.color): x.pieces for x in by_buyer[members[0].id].lines}
        second = {(x.size, x.color): x.pieces for x in by_buyer[members[1].id].lines}
        assert first[("S", "blue")] + second[("S", "blue")] == 25
        assert first[("S", "blue")] > second[("S", "blue")]
        assert all(o.status == OrderStatus.AWAITING_PAYMENT for o in orders)
        assert sum(o.pieces for o in orders) == lot.reserved_pieces

    def test_a_pool_below_the_minimum_is_not_placed(self, db: Session, lot) -> None:  # type: ignore[no-untyped-def]
        members = [_member(db, f"0300100000{n}") for n in range(1, 4)]
        pool = _open(db, lot, members[0], S=5)
        _join(db, pool, members[1], M=5)
        _join(db, pool, members[2], L=5)
        with pytest.raises(Conflict, match="15,000"):
            pool_service.place(db, actor=members[0], pool_id=pool.id)
        assert db.query(Order).count() == 0

    def test_too_few_members_is_not_placed(self, db: Session, lot) -> None:  # type: ignore[no-untyped-def]
        members = [_member(db, f"0300100000{n}") for n in range(1, 3)]
        pool = _open(db, lot, members[0], S=25)
        _join(db, pool, members[1], M=25, L=25)
        with pytest.raises(Conflict, match="more member"):
            pool_service.place(db, actor=members[0], pool_id=pool.id)

    def test_only_the_organiser_places(self, db: Session, lot) -> None:  # type: ignore[no-untyped-def]
        members = [_member(db, f"0300100000{n}") for n in range(1, 4)]
        pool = _open(db, lot, members[0], S=20)
        _join(db, pool, members[1], M=20)
        _join(db, pool, members[2], L=20)
        with pytest.raises(Forbidden):
            pool_service.place(db, actor=members[1], pool_id=pool.id)

    def test_an_expired_pool_closes(self, db: Session, lot) -> None:  # type: ignore[no-untyped-def]
        pool = _open(db, lot, _member(db, "03001000001"), S=20)
        later = datetime.now(UTC) + timedelta(days=30)
        assert pool_service.expire_pools(db, now=later) == 1
        assert pool.status == PoolStatus.EXPIRED


class TestEndpoints:
    def test_members_are_not_identified_to_each_other(
        self,
        client: TestClient,
        db: Session,
        lot,  # type: ignore[no-untyped-def]
    ) -> None:
        organiser = _member(db, "03001000001")
        neighbour = _member(db, "03001000002")
        body = {
            "lot_id": lot.id,
            "lines": _lines(S=20),
            "delivery_address": "Shop 3, Hussain Agahi",
            "delivery_phone": "03001234567",
            "payment_method": "jazzcash",
        }
        opened = client.post("/pools", json=body, headers=auth(organiser))
        assert opened.status_code == 201, opened.text

        listed = client.get("/pools", headers=auth(neighbour)).json()
        assert [p["id"] for p in listed] == [opened.json()["id"]]
        text = str(listed)
        assert organiser.phone not in text and "Hussain Agahi" not in text
        assert listed[0]["mine"] is None
        assert listed[0]["places_left"] == 3

    def test_a_reseller_in_another_city_cannot_see_the_pool(
        self,
        client: TestClient,
        db: Session,
        lot,  # type: ignore[no-untyped-def]
    ) -> None:
        pool = _open(db, lot, _member(db, "03001000001"), S=20)
        db.commit()
        outsider = _member(db, "03001000005", city="Karachi")
        assert client.get(f"/pools/{pool.id}", headers=auth(outsider)).status_code == 404
        assert client.get("/pools", headers=auth(outsider)).json() == []


def test_a_wildcard_city_does_not_list_other_cities_pools(db: Session, lot) -> None:  # type: ignore[no-untyped-def]
    """The city is matched exactly, so a profile city of "%" matches nothing else."""
    _open(db, lot, _member(db, "03001000001"), S=20)
    stranger = _member(db, "03001000009", city="%")
    assert pool_service.open_pools_for(db, stranger) == []
