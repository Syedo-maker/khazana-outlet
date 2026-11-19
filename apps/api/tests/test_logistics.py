"""Courier booking and the tracking updates that move an order."""

from __future__ import annotations

from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from commerce_helpers import auth, live_lot, make_courier, make_reseller, policy_for, whole_order
from khazana.core.errors import Conflict, Unauthenticated, ValidationFailed
from khazana.models import Brand, Lot, Order, Shipment, User
from khazana.models.base import utcnow
from khazana.models.enums import (
    OrderStatus,
    PaymentMethod,
    PaymentStatus,
    ShipmentStatus,
    Visibility,
)
from khazana.services import courier_providers, logistics_service, payment_service
from khazana.storage import read_object


@pytest.fixture(autouse=True)
def courier(db: Session):  # type: ignore[no-untyped-def]
    return make_courier(db)


@pytest.fixture
def seller(two_brands) -> tuple[Brand, User]:  # type: ignore[no-untyped-def]
    return two_brands[0]


@pytest.fixture
def buyer(db: Session) -> User:
    return make_reseller(db)


@pytest.fixture
def lot(db: Session, seller, category) -> Lot:  # type: ignore[no-untyped-def]
    brand, owner = seller
    return live_lot(db, brand, owner, category.id)


@pytest.fixture
def paid_order(db: Session, buyer: User, lot: Lot) -> Order:
    order = whole_order(db, buyer, lot)
    payment_service.complete_sandbox_payment(db, order=order, outcome="succeeded")
    db.commit()
    return order


@pytest.fixture
def shipment(db: Session, paid_order: Order, seller) -> Shipment:  # type: ignore[no-untyped-def]
    _, owner = seller
    booked = logistics_service.book_shipment(db, order=paid_order, actor=owner)
    db.commit()
    return booked


class TestBooking:
    def test_booking_prepares_the_order_and_stores_a_label(
        self, db: Session, paid_order: Order, shipment: Shipment
    ) -> None:
        assert OrderStatus(paid_order.status) == OrderStatus.PREPARING
        assert shipment.tracking_number
        assert ShipmentStatus(shipment.status) == ShipmentStatus.PENDING_PICKUP
        assert read_object(shipment.label_key or "").startswith(b"%PDF-")

    def test_an_unpaid_order_cannot_be_booked(
        self, db: Session, buyer: User, lot: Lot, seller
    ) -> None:  # type: ignore[no-untyped-def]
        _, owner = seller
        order = whole_order(db, buyer, lot)
        with pytest.raises(Conflict, match="being prepared"):
            logistics_service.book_shipment(db, order=order, actor=owner)

    def test_an_order_is_booked_once(
        self, db: Session, paid_order: Order, shipment: Shipment, seller
    ) -> None:  # type: ignore[no-untyped-def]
        _, owner = seller
        with pytest.raises(Conflict, match="already been booked"):
            logistics_service.book_shipment(db, order=paid_order, actor=owner)

    def test_the_label_never_names_the_brand(
        self, db: Session, buyer: User, seller, category
    ) -> None:  # type: ignore[no-untyped-def]
        from catalog_helpers import build_submitted_lot, review_photos
        from khazana.services import approval_service

        brand, owner = seller
        brand.unbranded_label = "Leading label"
        lot = build_submitted_lot(db, brand, owner, category.id, offset=40)
        review_photos(db, lot, owner)
        approval_service.approve(db, lot=lot, actor=owner, visibility=Visibility.UNBRANDED)
        db.commit()
        order = whole_order(db, buyer, lot)
        payment_service.complete_sandbox_payment(db, order=order, outcome="succeeded")
        booked = logistics_service.book_shipment(db, order=order, actor=owner)
        assert brand.name.encode() not in read_object(booked.label_key or "")

    def test_a_cod_label_states_the_amount_to_collect(
        self, db: Session, buyer: User, lot: Lot, seller
    ) -> None:  # type: ignore[no-untyped-def]
        brand, owner = seller
        policy_for(db, brand).allow_cod = True
        db.commit()
        order = whole_order(db, buyer, lot, method=PaymentMethod.COD)
        booked = logistics_service.book_shipment(db, order=order, actor=owner)
        assert f"{order.total_pkr:,} PKR".encode() in read_object(booked.label_key or "")


class TestTracking:
    def test_the_full_journey_moves_the_order(
        self, db: Session, paid_order: Order, shipment: Shipment
    ) -> None:
        logistics_service.advance_sandbox(db, shipment=shipment)
        assert OrderStatus(paid_order.status) == OrderStatus.SHIPPED
        logistics_service.advance_sandbox(db, shipment=shipment)
        assert OrderStatus(paid_order.status) == OrderStatus.SHIPPED
        logistics_service.advance_sandbox(db, shipment=shipment)
        db.commit()
        assert OrderStatus(paid_order.status) == OrderStatus.DELIVERED
        assert paid_order.dispute_window_ends_at is not None
        with pytest.raises(Conflict, match="no further steps"):
            logistics_service.advance_sandbox(db, shipment=shipment)

    def test_delivery_collects_cash_on_a_cod_order(
        self, db: Session, buyer: User, lot: Lot, seller
    ) -> None:  # type: ignore[no-untyped-def]
        brand, owner = seller
        policy_for(db, brand).allow_cod = True
        db.commit()
        order = whole_order(db, buyer, lot, method=PaymentMethod.COD)
        payment = payment_service.ensure_payment(db, order)
        booked = logistics_service.book_shipment(db, order=order, actor=owner)
        for _ in range(3):
            logistics_service.advance_sandbox(db, shipment=booked)
        assert PaymentStatus(payment.status) == PaymentStatus.HELD

    def test_a_step_cannot_be_skipped_backwards(self, db: Session, shipment: Shipment) -> None:
        logistics_service.apply_tracking(db, shipment=shipment, status=ShipmentStatus.PICKED_UP)
        with pytest.raises(Conflict, match="cannot become pending_pickup"):
            logistics_service.apply_tracking(
                db, shipment=shipment, status=ShipmentStatus.PENDING_PICKUP
            )

    def test_a_repeated_callback_is_applied_once(self, db: Session, shipment: Shipment) -> None:
        courier = courier_providers.sandbox_courier()
        body, signature = courier.build_callback(
            tracking_number=shipment.tracking_number or "", status=ShipmentStatus.PICKED_UP
        )
        for _ in range(2):
            logistics_service.ingest_callback(
                db, courier_code=courier.code, body=body, signature=signature
            )
        picked = [e for e in shipment.events if e.status == ShipmentStatus.PICKED_UP]
        assert len(picked) == 1

    def test_a_forged_callback_is_refused(self, db: Session, shipment: Shipment) -> None:
        courier = courier_providers.sandbox_courier()
        body, _ = courier.build_callback(
            tracking_number=shipment.tracking_number or "", status=ShipmentStatus.DELIVERED
        )
        with pytest.raises(Unauthenticated):
            logistics_service.ingest_callback(
                db, courier_code=courier.code, body=body, signature="forged"
            )

    def test_a_pickup_must_be_in_the_future(self, db: Session, shipment: Shipment) -> None:
        with pytest.raises(ValidationFailed, match="future"):
            logistics_service.schedule_pickup(
                db, shipment=shipment, when=utcnow() - timedelta(hours=1)
            )
        logistics_service.schedule_pickup(db, shipment=shipment, when=utcnow() + timedelta(days=1))
        assert shipment.pickup_scheduled_for is not None


class TestApi:
    def test_the_brand_books_and_both_sides_can_track(
        self, client: TestClient, paid_order: Order, buyer: User, seller
    ) -> None:  # type: ignore[no-untyped-def]
        _, owner = seller
        created = client.post(f"/orders/{paid_order.id}/shipments", headers=auth(owner))
        assert created.status_code == 201, created.text
        assert created.json()["cost_pkr"] == 2_300

        as_buyer = client.get(f"/orders/{paid_order.id}/tracking", headers=auth(buyer)).json()
        assert as_buyer[0]["tracking_number"] == created.json()["tracking_number"]
        assert as_buyer[0]["cost_pkr"] is None

    def test_the_label_is_for_the_brand_only(
        self, client: TestClient, shipment: Shipment, buyer: User, seller, two_brands
    ) -> None:  # type: ignore[no-untyped-def]
        _, owner = seller
        _, competitor = two_brands[1]
        url = f"/shipments/{shipment.id}/label"
        response = client.get(url, headers=auth(owner))
        assert response.status_code == 200
        assert response.headers["content-type"] == "application/pdf"
        assert client.get(url, headers=auth(competitor)).status_code == 404
        assert client.get(url, headers=auth(buyer)).status_code == 403

    def test_another_buyer_cannot_track(
        self, client: TestClient, db: Session, shipment: Shipment, paid_order: Order
    ) -> None:
        stranger = make_reseller(db, phone="03001112222")
        response = client.get(f"/orders/{paid_order.id}/tracking", headers=auth(stranger))
        assert response.status_code == 404
