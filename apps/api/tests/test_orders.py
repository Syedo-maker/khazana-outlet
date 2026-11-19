"""Ordering: stock, money, access and the lifecycle."""

from __future__ import annotations

from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from commerce_helpers import (
    DELIVERY,
    DELIVERY_JSON,
    auth,
    live_lot,
    make_courier,
    make_reseller,
    open_for_part_orders,
    part_order,
    policy_for,
    whole_order,
)
from khazana.core.errors import Conflict, Forbidden, NotFound, ValidationFailed
from khazana.models import Brand, Lot, ShippingRate, User
from khazana.models.base import utcnow
from khazana.models.enums import (
    LotStatus,
    OrderStatus,
    PaymentMethod,
    VerificationStatus,
)
from khazana.services import approval_service, catalog_service, logistics_service, order_service
from khazana.services.order_service import Purchase


@pytest.fixture(autouse=True)
def courier(db: Session):  # type: ignore[no-untyped-def]
    return make_courier(db)


@pytest.fixture
def seller(two_brands) -> tuple[Brand, User]:  # type: ignore[no-untyped-def]
    return two_brands[0]


@pytest.fixture
def other_seller(two_brands) -> tuple[Brand, User]:  # type: ignore[no-untyped-def]
    return two_brands[1]


@pytest.fixture
def buyer(db: Session) -> User:
    return make_reseller(db)


@pytest.fixture
def lot(db: Session, seller, category) -> Lot:  # type: ignore[no-untyped-def]
    brand, owner = seller
    return live_lot(db, brand, owner, category.id)


def advance_to_delivered(db: Session, order) -> None:  # type: ignore[no-untyped-def]
    order_service.mark_paid(db, order)
    order_service._move(db, order, OrderStatus.PREPARING, actor=None)
    order_service.mark_shipped(db, order)
    order_service.mark_delivered(db, order)
    db.commit()


class TestPricingAndStock:
    def test_a_whole_lot_order_reserves_everything_and_adds_up(
        self, db: Session, buyer: User, lot: Lot
    ) -> None:
        order = whole_order(db, buyer, lot)

        assert order.pieces == 100
        assert order.subtotal_pkr == 30_000
        # 100 pieces at 300 g is 30 kg: 500 + 30 x 60.
        assert order.shipping_pkr == 2_300
        assert order.total_pkr == 32_300
        assert order.commission_pkr == 4_500
        assert order.brand_payout_pkr == 25_500
        assert lot.reserved_pieces == 100
        assert OrderStatus(order.status) == OrderStatus.AWAITING_PAYMENT

    def test_the_commission_is_copied_onto_the_order(
        self, db: Session, buyer: User, lot: Lot, seller
    ) -> None:  # type: ignore[no-untyped-def]
        brand, _ = seller
        order = whole_order(db, buyer, lot)
        policy_for(db, brand).commission_percent = 40
        db.commit()
        db.refresh(order)
        assert float(order.commission_percent) == 15

    def test_stock_cannot_be_sold_twice(self, db: Session, buyer: User, lot: Lot) -> None:
        whole_order(db, buyer, lot)
        second = make_reseller(db, phone="03008888888")
        with pytest.raises(NotFound):
            whole_order(db, second, lot)

    def test_part_orders_add_up_to_the_listed_price(
        self, db: Session, buyer: User, seller, category
    ) -> None:  # type: ignore[no-untyped-def]
        brand, owner = seller
        open_for_part_orders(db, brand)
        lot = live_lot(db, brand, owner, category.id, offset=5, lot_price_pkr=30_001)

        first = part_order(db, buyer, lot, [("S", "blue", 25)])
        assert first.unit_price_pkr == 301
        assert first.subtotal_pkr == 7_525

        rest = whole_order(db, buyer, lot)
        assert rest.pieces == 75
        assert first.subtotal_pkr + rest.subtotal_pkr == 30_001
        assert rest.subtotal_pkr == rest.pieces * rest.unit_price_pkr + rest.rounding_adjustment_pkr

    def test_a_size_cannot_be_oversold(self, db: Session, buyer: User, seller, category) -> None:  # type: ignore[no-untyped-def]
        brand, owner = seller
        open_for_part_orders(db, brand)
        lot = live_lot(db, brand, owner, category.id, offset=6)
        part_order(db, buyer, lot, [("S", "blue", 20)])
        with pytest.raises(Conflict, match="Only 5 pieces"):
            part_order(db, buyer, lot, [("S", "blue", 10)])

    def test_the_minimum_order_applies(self, db: Session, buyer: User, seller, category) -> None:  # type: ignore[no-untyped-def]
        brand, owner = seller
        open_for_part_orders(db, brand)
        lot = live_lot(db, brand, owner, category.id, offset=7)
        with pytest.raises(ValidationFailed, match="minimum order"):
            part_order(db, buyer, lot, [("S", "blue", 5)])

    def test_the_minimum_value_applies(self, db: Session, buyer: User, seller, category) -> None:  # type: ignore[no-untyped-def]
        brand, owner = seller
        policy = open_for_part_orders(db, brand)
        policy.min_lot_value_pkr = 25_000
        db.commit()
        lot = live_lot(db, brand, owner, category.id, offset=8)
        with pytest.raises(ValidationFailed, match="minimum order value"):
            part_order(db, buyer, lot, [("S", "blue", 25)])

    def test_part_orders_need_the_brands_permission(
        self, db: Session, buyer: User, lot: Lot
    ) -> None:
        with pytest.raises(ValidationFailed, match="only as a whole"):
            part_order(db, buyer, lot, [("S", "blue", 25)])

    def test_a_cancelled_order_returns_its_stock(self, db: Session, buyer: User, lot: Lot) -> None:
        order = whole_order(db, buyer, lot)
        order_service.cancel(db, order, actor=buyer, reason="Ordered by mistake")
        db.commit()
        assert lot.reserved_pieces == 0
        assert whole_order(db, buyer, lot).pieces == 100

    def test_material_edits_are_refused_once_ordered(
        self, db: Session, buyer: User, lot: Lot, seller
    ) -> None:  # type: ignore[no-untyped-def]
        _, owner = seller
        whole_order(db, buyer, lot)
        with pytest.raises(Conflict, match="already ordered"):
            catalog_service.update_lot(db, lot=lot, actor=owner, changes={"lot_price_pkr": 40_000})


class TestWhoCanOrder:
    def test_the_region_lock_follows_the_delivery_city(
        self, db: Session, buyer: User, lot: Lot, seller
    ) -> None:  # type: ignore[no-untyped-def]
        _, owner = seller
        approval_service.set_region_lock(db, lot=lot, actor=owner, cities=["Multan"])
        db.commit()
        with pytest.raises(NotFound):
            whole_order(db, buyer, lot)

    def test_an_unverified_business_cannot_order(self, db: Session, lot: Lot) -> None:
        buyer = make_reseller(db, phone="03006666666", status=VerificationStatus.PENDING)
        with pytest.raises(Forbidden, match="verified"):
            whole_order(db, buyer, lot)

    def test_a_brand_account_cannot_order(self, db: Session, lot: Lot, other_seller) -> None:  # type: ignore[no-untyped-def]
        _, competitor = other_seller
        with pytest.raises(Forbidden):
            whole_order(db, competitor, lot)

    def test_cod_needs_the_brands_permission(self, db: Session, buyer: User, lot: Lot) -> None:
        with pytest.raises(ValidationFailed, match="Cash on delivery"):
            whole_order(db, buyer, lot, method=PaymentMethod.COD)

    def test_a_cod_order_goes_straight_to_preparation(
        self, db: Session, buyer: User, lot: Lot, seller
    ) -> None:  # type: ignore[no-untyped-def]
        brand, _ = seller
        policy_for(db, brand).allow_cod = True
        db.commit()
        order = whole_order(db, buyer, lot, method=PaymentMethod.COD)
        assert OrderStatus(order.status) == OrderStatus.PREPARING

    def test_a_bad_phone_number_is_refused(self, db: Session, buyer: User, lot: Lot) -> None:
        delivery = order_service.Delivery(city="Multan", address="Shop 1, Bazaar", phone="12345")
        with pytest.raises(ValidationFailed, match="11 digit"):
            order_service.place_orders(
                db,
                buyer=buyer,
                purchases=[Purchase(lot_id=lot.id)],
                delivery=delivery,
                method=PaymentMethod.JAZZCASH,
            )


class TestLifecycle:
    def test_statuses_cannot_be_skipped(self, db: Session, buyer: User, lot: Lot) -> None:
        order = whole_order(db, buyer, lot)
        with pytest.raises(Conflict, match="cannot become shipped"):
            order_service.mark_shipped(db, order)

    def test_a_paid_order_cannot_simply_be_cancelled(
        self, db: Session, buyer: User, lot: Lot
    ) -> None:
        order = whole_order(db, buyer, lot)
        order_service.mark_paid(db, order)
        with pytest.raises(Conflict, match="cannot be cancelled"):
            order_service.cancel(db, order, actor=buyer, reason="Changed my mind")

    def test_confirmation_finishes_the_order_and_sells_the_lot(
        self, db: Session, buyer: User, lot: Lot
    ) -> None:
        order = whole_order(db, buyer, lot)
        advance_to_delivered(db, order)
        assert order.dispute_window_ends_at is not None

        order_service.confirm_delivery(db, order, actor=buyer)
        db.commit()
        assert OrderStatus(order.status) == OrderStatus.CONFIRMED
        assert LotStatus(lot.status) == LotStatus.SOLD
        assert [event.to_status for event in order.events][-1] == OrderStatus.CONFIRMED

    def test_an_unconfirmed_order_closes_when_the_window_ends(
        self, db: Session, buyer: User, lot: Lot
    ) -> None:
        order = whole_order(db, buyer, lot)
        advance_to_delivered(db, order)
        assert order_service.close_expired_windows(db) == 0

        later = utcnow() + timedelta(days=4)
        assert order_service.close_expired_windows(db, now=later) == 1
        assert OrderStatus(order.status) == OrderStatus.CONFIRMED

    def test_a_problem_can_be_reported_inside_the_window(
        self, db: Session, buyer: User, lot: Lot
    ) -> None:
        order = whole_order(db, buyer, lot)
        advance_to_delivered(db, order)
        order_service.open_dispute(
            db, order, actor=buyer, reason="Short delivered", detail="10 pieces missing"
        )
        db.commit()
        assert OrderStatus(order.status) == OrderStatus.DISPUTED
        assert order_service.close_expired_windows(db, now=utcnow() + timedelta(days=9)) == 0

    def test_a_problem_cannot_be_reported_after_the_window(
        self, db: Session, buyer: User, lot: Lot
    ) -> None:
        order = whole_order(db, buyer, lot)
        advance_to_delivered(db, order)
        order.dispute_window_ends_at = utcnow() - timedelta(minutes=1)
        db.commit()
        with pytest.raises(Conflict, match="has passed"):
            order_service.open_dispute(db, order, actor=buyer, reason="Late", detail=None)

    def test_returns_cannot_exceed_the_order(
        self, db: Session, buyer: User, lot: Lot, seller
    ) -> None:  # type: ignore[no-untyped-def]
        _, owner = seller
        order = whole_order(db, buyer, lot)
        advance_to_delivered(db, order)
        order_service.record_return(db, order, actor=owner, pieces=60, reason="Wrong size")
        with pytest.raises(ValidationFailed, match="Up to 40"):
            order_service.record_return(db, order, actor=owner, pieces=41, reason="Damaged")


class TestShippingRates:
    def test_the_most_specific_rate_wins(self, db: Session, courier, lot: Lot) -> None:  # type: ignore[no-untyped-def]
        courier.rates.append(ShippingRate(destination_city="multan", base_pkr=100, per_kg_pkr=10))
        db.commit()
        assert logistics_service.quote(
            db, lot=lot, pieces=10, destination_city="Multan"
        ).cost_pkr == (130)
        assert logistics_service.quote(
            db, lot=lot, pieces=10, destination_city="Quetta"
        ).cost_pkr == (680)

    def test_a_stated_lot_weight_is_used(self, db: Session, lot: Lot) -> None:
        lot.weight_kg = 50
        db.commit()
        assert logistics_service.quote(
            db, lot=lot, pieces=10, destination_city="Multan"
        ).weight_kg == (5)


class TestApiAccess:
    def _order(self, client: TestClient, buyer: User, lot: Lot) -> dict[str, object]:
        response = client.post(
            "/orders",
            json={
                **DELIVERY_JSON,
                "payment_method": "jazzcash",
                "purchase": {"lot_id": lot.id},
            },
            headers=auth(buyer),
        )
        assert response.status_code == 201, response.text
        return dict(response.json())

    def test_a_buyer_sees_no_commission_or_brand_identity(
        self, client: TestClient, buyer: User, lot: Lot, seller
    ) -> None:  # type: ignore[no-untyped-def]
        brand, _ = seller
        body = self._order(client, buyer, lot)
        assert body["commission_pkr"] is None
        assert body["brand_payout_pkr"] is None
        assert brand.id not in str(body)
        assert body["delivery_address"] == DELIVERY.address

    def test_a_brand_sees_its_money_but_not_an_unpaid_buyers_address(
        self, client: TestClient, buyer: User, lot: Lot, seller
    ) -> None:  # type: ignore[no-untyped-def]
        _, owner = seller
        created = self._order(client, buyer, lot)
        body = client.get(f"/orders/{created['id']}", headers=auth(owner)).json()
        assert body["commission_pkr"] == 4_500
        assert body["delivery_address"] is None

    def test_strangers_get_a_404(
        self, client: TestClient, db: Session, buyer: User, lot: Lot, other_seller
    ) -> None:  # type: ignore[no-untyped-def]
        _, competitor = other_seller
        stranger = make_reseller(db, phone="03005555555")
        created = self._order(client, buyer, lot)
        for user in (competitor, stranger):
            assert client.get(f"/orders/{created['id']}", headers=auth(user)).status_code == 404

    def test_each_side_lists_only_its_own_orders(
        self, client: TestClient, db: Session, buyer: User, lot: Lot, seller, other_seller
    ) -> None:  # type: ignore[no-untyped-def]
        _, owner = seller
        _, competitor = other_seller
        self._order(client, buyer, lot)
        assert len(client.get("/orders", headers=auth(buyer)).json()) == 1
        assert len(client.get("/orders", headers=auth(owner)).json()) == 1
        assert client.get("/orders", headers=auth(competitor)).json() == []

    def test_only_the_buyer_can_confirm(
        self, client: TestClient, db: Session, buyer: User, lot: Lot, seller
    ) -> None:  # type: ignore[no-untyped-def]
        _, owner = seller
        order = whole_order(db, buyer, lot)
        advance_to_delivered(db, order)
        assert client.post(f"/orders/{order.id}/confirm", headers=auth(owner)).status_code == 404
        assert client.post(f"/orders/{order.id}/confirm", headers=auth(buyer)).status_code == 200

    def test_a_sold_out_lot_leaves_the_catalogue(
        self, client: TestClient, db: Session, buyer: User, lot: Lot
    ) -> None:
        assert client.get("/catalog", headers=auth(buyer)).json()["total"] == 1
        whole_order(db, buyer, lot)
        assert client.get("/catalog", headers=auth(buyer)).json()["total"] == 0


class TestCart:
    def test_add_view_and_checkout(
        self, client: TestClient, db: Session, buyer: User, lot: Lot
    ) -> None:
        added = client.put(f"/cart/items/{lot.id}", json={}, headers=auth(buyer))
        assert added.status_code == 200, added.text

        cart = client.get("/cart", headers=auth(buyer)).json()
        assert cart["items"][0]["subtotal_pkr"] == 30_000
        assert cart["total_pkr"] == 32_300
        # Nothing is reserved until checkout.
        db.refresh(lot)
        assert lot.reserved_pieces == 0

        orders = client.post(
            "/cart/checkout",
            json={**DELIVERY_JSON, "payment_method": "bank_transfer"},
            headers=auth(buyer),
        )
        assert orders.status_code == 201, orders.text
        assert len(orders.json()) == 1
        assert client.get("/cart", headers=auth(buyer)).json()["items"] == []

    def test_a_problem_is_reported_on_the_item(
        self, client: TestClient, db: Session, buyer: User, lot: Lot
    ) -> None:
        client.put(f"/cart/items/{lot.id}", json={}, headers=auth(buyer))
        other = make_reseller(db, phone="03004444444")
        whole_order(db, other, lot)
        cart = client.get("/cart", headers=auth(buyer)).json()
        assert "not available" in cart["items"][0]["problem"]
        assert cart["total_pkr"] == 0

    def test_checkout_is_all_or_nothing(
        self, db: Session, buyer: User, lot: Lot, seller, category
    ) -> None:  # type: ignore[no-untyped-def]
        brand, owner = seller
        second = live_lot(db, brand, owner, category.id, offset=9)
        approval_service.set_region_lock(db, lot=second, actor=owner, cities=["Multan"])
        db.commit()

        with pytest.raises(NotFound):
            order_service.place_orders(
                db,
                buyer=buyer,
                purchases=[Purchase(lot_id=lot.id), Purchase(lot_id=second.id)],
                delivery=DELIVERY,
                method=PaymentMethod.JAZZCASH,
            )
        db.rollback()
        db.refresh(lot)
        assert lot.reserved_pieces == 0
        assert order_service.list_orders(db, buyer_user_id=buyer.id) == []
