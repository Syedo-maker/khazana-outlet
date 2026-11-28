"""Cash on delivery, direct to the brand: the pilot's order mode.

The platform never holds the buyer's money. The buyer pays the brand's own
courier on delivery; the brand, or an admin, enters the tracking number by
hand and records the delivery; the platform records the commission the brand
owes and invoices it monthly. The payment and courier integrations are not
touched by any of this.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from commerce_helpers import (
    DELIVERY_JSON,
    auth,
    live_lot,
    make_courier,
    make_reseller,
    policy_for,
    whole_order,
)
from khazana.config import get_settings
from khazana.core.errors import Conflict, ValidationFailed
from khazana.models import Lot, Order, Payment, Payout
from khazana.models.enums import (
    OrderStatus,
    PaymentMethod,
    SettlementMode,
    ShipmentStatus,
)
from khazana.services import commission_service, order_service


@pytest.fixture
def seller(db: Session, two_brands):  # type: ignore[no-untyped-def]
    (brand, owner), _ = two_brands
    make_courier(db)
    policy = policy_for(db, brand)
    policy.settlement_mode = SettlementMode.DIRECT
    policy.allow_cod = True
    policy.commission_percent = Decimal(10)
    db.commit()
    return brand, owner


@pytest.fixture
def lot(db: Session, seller, category) -> Lot:  # type: ignore[no-untyped-def]
    brand, owner = seller
    return live_lot(db, brand, owner, category.id)


@pytest.fixture
def buyer(db: Session):  # type: ignore[no-untyped-def]
    return make_reseller(db)


def _order(db: Session, buyer, lot: Lot) -> Order:  # type: ignore[no-untyped-def]
    return whole_order(db, buyer, lot, method=PaymentMethod.COD)


def _ship(client: TestClient, order: Order, user, tracking: str = "TCS-100200300"):  # type: ignore[no-untyped-def]
    return client.post(
        f"/orders/{order.id}/shipments/manual",
        json={"courier": "TCS", "tracking_number": tracking},
        headers=auth(user),
    )


class TestPlacing:
    def test_a_direct_order_holds_no_money(self, db: Session, buyer, lot: Lot) -> None:  # type: ignore[no-untyped-def]
        order = _order(db, buyer, lot)
        assert SettlementMode(order.settlement_mode) == SettlementMode.DIRECT
        assert OrderStatus(order.status) == OrderStatus.PREPARING
        assert db.scalars(select(Payment).where(Payment.order_id == order.id)).first() is None

    def test_checkout_over_http_creates_no_payment(
        self, client: TestClient, db: Session, buyer, lot: Lot
    ) -> None:  # type: ignore[no-untyped-def]
        response = client.post(
            "/orders",
            json={
                **DELIVERY_JSON,
                "payment_method": "cod",
                "purchase": {"lot_id": lot.id, "whole_lot": True},
            },
            headers=auth(buyer),
        )
        assert response.status_code == 201, response.text
        assert response.json()["settlement_mode"] == "direct"
        assert db.scalars(select(Payment)).first() is None

    def test_only_cash_on_delivery_is_offered(self, db: Session, buyer, lot: Lot) -> None:  # type: ignore[no-untyped-def]
        with pytest.raises(ValidationFailed, match="cash on delivery"):
            whole_order(db, buyer, lot, method=PaymentMethod.JAZZCASH)

    def test_new_brands_default_to_direct_for_the_pilot(self, db: Session) -> None:
        from khazana.services import brand_service

        assert get_settings().default_settlement_mode == SettlementMode.DIRECT
        assert brand_service.default_settlement_mode() == SettlementMode.DIRECT


class TestManualShipping:
    def test_the_brand_enters_the_tracking_number(
        self, client: TestClient, db: Session, buyer, lot: Lot, seller
    ) -> None:  # type: ignore[no-untyped-def]
        _, owner = seller
        order = _order(db, buyer, lot)
        response = _ship(client, order, owner)
        assert response.status_code == 201, response.text
        assert response.json()["courier"] == "TCS"
        db.refresh(order)
        assert OrderStatus(order.status) == OrderStatus.SHIPPED
        assert order.shipments[0].label_key is None, "no label: the brand's courier made one"

    def test_an_admin_can_enter_it_too(
        self, client: TestClient, db: Session, buyer, lot: Lot, admin_user
    ) -> None:  # type: ignore[no-untyped-def]
        order = _order(db, buyer, lot)
        assert _ship(client, order, admin_user).status_code == 201

    def test_another_brand_and_the_buyer_cannot(
        self, client: TestClient, db: Session, buyer, lot: Lot, two_brands
    ) -> None:  # type: ignore[no-untyped-def]
        _, (_, other_owner) = two_brands
        order = _order(db, buyer, lot)
        assert _ship(client, order, other_owner).status_code in (403, 404)
        assert _ship(client, order, buyer).status_code in (403, 404)

    def test_a_tracking_number_is_used_once(
        self, client: TestClient, db: Session, buyer, lot: Lot, seller, category
    ) -> None:  # type: ignore[no-untyped-def]
        brand, owner = seller
        first = _order(db, buyer, lot)
        second = _order(
            db,
            make_reseller(db, phone="03004444441"),
            live_lot(db, brand, owner, category.id, offset=50),
        )
        assert _ship(client, first, owner).status_code == 201
        assert _ship(client, second, owner).status_code == 409

    def test_platform_settled_orders_keep_the_courier_integration(
        self, client: TestClient, db: Session, two_brands, category
    ) -> None:  # type: ignore[no-untyped-def]
        _, (other_brand, other_owner) = two_brands
        make_courier(db)
        policy = policy_for(db, other_brand)
        policy.allow_cod = True
        db.commit()
        platform_lot = live_lot(db, other_brand, other_owner, category.id, offset=80)
        order = whole_order(
            db, make_reseller(db, phone="03004444442"), platform_lot, method=PaymentMethod.COD
        )
        assert SettlementMode(order.settlement_mode) == SettlementMode.PLATFORM
        assert _ship(client, order, other_owner).status_code == 409


def _deliver(client: TestClient, order: Order, user, status: str = "delivered"):  # type: ignore[no-untyped-def]
    shipment_id = order.shipments[0].id
    return client.post(
        f"/shipments/{shipment_id}/manual-status",
        json={"status": status, "note": "Courier confirmed by phone."},
        headers=auth(user),
    )


class TestDelivery:
    def test_delivery_then_confirmation_creates_no_payout(
        self, client: TestClient, db: Session, buyer, lot: Lot, seller
    ) -> None:  # type: ignore[no-untyped-def]
        _, owner = seller
        order = _order(db, buyer, lot)
        _ship(client, order, owner)
        db.refresh(order)
        assert _deliver(client, order, owner).status_code == 200
        db.refresh(order)
        assert OrderStatus(order.status) == OrderStatus.DELIVERED
        order_service.confirm_delivery(db, order, actor=buyer)
        db.commit()
        assert OrderStatus(order.status) == OrderStatus.CONFIRMED
        assert db.scalars(select(Payout)).first() is None, "the brand already has the cash"

    def test_a_refused_delivery_cancels_and_returns_the_stock(
        self, client: TestClient, db: Session, buyer, lot: Lot, seller
    ) -> None:  # type: ignore[no-untyped-def]
        _, owner = seller
        before = lot.available_pieces
        order = _order(db, buyer, lot)
        _ship(client, order, owner)
        db.refresh(order)
        assert _deliver(client, order, owner, status="returned").status_code == 200
        db.refresh(order)
        db.refresh(lot)
        assert OrderStatus(order.status) == OrderStatus.CANCELLED
        assert ShipmentStatus(order.shipments[0].status) == ShipmentStatus.RETURNED
        assert lot.available_pieces == before


def _confirmed(
    db: Session, client: TestClient, buyer, lot: Lot, owner, tracking: str, when: datetime
) -> Order:  # type: ignore[no-untyped-def]
    order = _order(db, buyer, lot)
    _ship(client, order, owner, tracking=tracking)
    db.refresh(order)
    _deliver(client, order, owner)
    db.refresh(order)
    order_service.confirm_delivery(db, order, actor=buyer)
    order.confirmed_at = when
    db.commit()
    return order


class TestCommissionInvoices:
    def test_a_month_of_orders_becomes_one_invoice_per_brand(
        self, client: TestClient, db: Session, buyer, seller, category
    ) -> None:  # type: ignore[no-untyped-def]
        brand, owner = seller
        november = datetime(2026, 11, 10, tzinfo=UTC)
        lots = [live_lot(db, brand, owner, category.id, offset=100 + n) for n in range(3)]
        first = _confirmed(db, client, buyer, lots[0], owner, "TCS-1", november)
        second = _confirmed(
            db, client, make_reseller(db, phone="03004444443"), lots[1], owner, "TCS-2", november
        )
        _confirmed(
            db,
            client,
            make_reseller(db, phone="03004444444"),
            lots[2],
            owner,
            "TCS-3",
            november + timedelta(days=25),
        )

        invoices = commission_service.issue_month(db, year=2026, month=11)
        db.commit()
        assert len(invoices) == 1
        invoice = invoices[0]
        assert invoice.brand_id == brand.id
        assert invoice.order_count == 2, "December's order waits for December's invoice"
        assert invoice.commission_pkr == first.commission_pkr + second.commission_pkr
        assert invoice.number.startswith("KO-2026-11-")

        assert commission_service.issue_month(db, year=2026, month=11) == [], (
            "issuing twice adds nothing"
        )

    def test_platform_settled_and_cancelled_orders_are_not_invoiced(
        self, client: TestClient, db: Session, buyer, lot: Lot, seller
    ) -> None:  # type: ignore[no-untyped-def]
        _, owner = seller
        order = _order(db, buyer, lot)
        _ship(client, order, owner)
        db.refresh(order)
        _deliver(client, order, owner, status="returned")
        assert commission_service.issue_month(db, year=2026, month=11) == []

    def test_a_partial_refund_reduces_the_commission(
        self, client: TestClient, db: Session, buyer, lot: Lot, seller, admin_user
    ) -> None:  # type: ignore[no-untyped-def]
        from khazana.services import payment_service

        _, owner = seller
        order = _order(db, buyer, lot)
        _ship(client, order, owner)
        db.refresh(order)
        _deliver(client, order, owner)
        db.refresh(order)
        dispute = order_service.open_dispute(db, order, actor=buyer, reason="Short", detail=None)
        refund = order.subtotal_pkr // 4
        payment_service.resolve_dispute(
            db,
            dispute=dispute,
            admin=admin_user,
            resolution="The brand refunds a quarter directly to the buyer.",
            refund_pkr=refund,
        )
        order.confirmed_at = datetime(2026, 11, 12, tzinfo=UTC)
        db.commit()
        invoice = commission_service.issue_month(db, year=2026, month=11)[0]
        expected = round((order.subtotal_pkr - refund) * float(order.commission_percent) / 100)
        assert invoice.commission_pkr == expected

    def test_a_brand_sees_only_its_own_invoices_and_an_admin_marks_one_paid(
        self, client: TestClient, db: Session, buyer, lot: Lot, seller, two_brands, admin_user
    ) -> None:  # type: ignore[no-untyped-def]
        brand, owner = seller
        _, (_, other_owner) = two_brands
        _confirmed(db, client, buyer, lot, owner, "TCS-9", datetime(2026, 11, 5, tzinfo=UTC))
        invoice = commission_service.issue_month(db, year=2026, month=11)[0]
        db.commit()

        mine = client.get(f"/brands/{brand.id}/commission-invoices", headers=auth(owner))
        assert mine.status_code == 200
        assert [row["id"] for row in mine.json()] == [invoice.id]
        assert client.get(
            f"/brands/{brand.id}/commission-invoices", headers=auth(other_owner)
        ).status_code in (403, 404)
        detail = client.get(f"/commission-invoices/{invoice.id}", headers=auth(owner)).json()
        assert len(detail["lines"]) == 1
        assert client.get(
            f"/commission-invoices/{invoice.id}", headers=auth(other_owner)
        ).status_code in (403, 404)

        assert (
            client.post(
                f"/admin/commission-invoices/{invoice.id}/paid",
                json={"reference": "IBFT-22"},
                headers=auth(owner),
            ).status_code
            == 403
        )
        paid = client.post(
            f"/admin/commission-invoices/{invoice.id}/paid",
            json={"reference": "IBFT-22"},
            headers=auth(admin_user),
        )
        assert paid.status_code == 200, paid.text
        assert paid.json()["status"] == "paid"
        with pytest.raises(Conflict):
            commission_service.mark_paid(
                db, invoice_id=invoice.id, admin=admin_user, reference="again"
            )

    def test_the_scheduler_issues_last_month_on_the_first(self) -> None:
        from khazana.scheduler import JOBS, PKT

        job = next(job for job in JOBS if job.name == "commission-invoices")
        due = job.next_after(datetime(2026, 11, 20, 12, 0, tzinfo=PKT)).astimezone(PKT)
        assert (due.day, due.month, due.hour) == (1, 12, 6)


class TestWhatTheBuyerIsTold:
    def test_the_lot_page_says_the_brand_is_paid_on_delivery(
        self, client: TestClient, buyer, lot: Lot
    ) -> None:  # type: ignore[no-untyped-def]
        detail = client.get(f"/catalog/{lot.id}", headers=auth(buyer)).json()
        assert detail["pays_brand_directly"] is True
        assert detail["allows_cod"] is True

    def test_the_cart_offers_cash_on_delivery_only(
        self, client: TestClient, buyer, lot: Lot
    ) -> None:  # type: ignore[no-untyped-def]
        client.put(f"/cart/items/{lot.id}", json={"whole_lot": True}, headers=auth(buyer))
        cart = client.get("/cart", headers=auth(buyer)).json()
        assert cart["cash_on_delivery_only"] is True
        assert cart["items"][0]["pays_brand_directly"] is True

    def test_there_is_nothing_to_pay_online(
        self, client: TestClient, db: Session, buyer, lot: Lot
    ) -> None:  # type: ignore[no-untyped-def]
        order = _order(db, buyer, lot)
        response = client.post(f"/orders/{order.id}/payment", headers=auth(buyer))
        assert response.status_code == 409
        assert "courier" in response.text


class TestSwitchingABrand:
    def test_only_an_admin_changes_how_a_brand_is_paid(
        self, client: TestClient, db: Session, seller, admin_user
    ) -> None:  # type: ignore[no-untyped-def]
        brand, owner = seller
        refused = client.patch(
            f"/brands/{brand.id}/policy", json={"settlement_mode": "platform"}, headers=auth(owner)
        )
        assert refused.status_code in (403, 422)
        changed = client.patch(
            f"/admin/brands/{brand.id}/terms",
            json={"settlement_mode": "platform"},
            headers=auth(admin_user),
        )
        assert changed.status_code == 200, changed.text
        db.refresh(policy_for(db, brand))
        assert SettlementMode(policy_for(db, brand).settlement_mode) == SettlementMode.PLATFORM
