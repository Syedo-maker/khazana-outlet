"""Held funds: when money counts as received, released and returned."""

from __future__ import annotations

import json
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from commerce_helpers import auth, live_lot, make_courier, make_reseller, policy_for, whole_order
from khazana.config import get_settings
from khazana.core.errors import Conflict, Unauthenticated, ValidationFailed
from khazana.models import Brand, Dispute, Lot, Order, PaymentEvent, Payout, User
from khazana.models.base import utcnow
from khazana.models.enums import (
    DisputeStatus,
    OrderStatus,
    PaymentMethod,
    PaymentStatus,
    PayoutStatus,
)
from khazana.services import order_service, payment_providers, payment_service


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
def order(db: Session, buyer: User, lot: Lot) -> Order:
    created = whole_order(db, buyer, lot)
    payment_service.ensure_payment(db, created)
    db.commit()
    return created


def callback(order: Order, *, outcome: str = "succeeded", amount: int | None = None):  # type: ignore[no-untyped-def]
    payment = order.payments[0]
    provider = payment_providers.wallet_named(payment.provider or "")
    return provider, provider.build_callback(
        reference=payment.provider_reference or "",
        outcome=outcome,  # type: ignore[arg-type]
        amount_pkr=payment.amount_pkr if amount is None else amount,
    )


def pay(db: Session, order: Order) -> None:
    payment_service.complete_sandbox_payment(db, order=order, outcome="succeeded")
    db.commit()


def deliver(db: Session, order: Order) -> None:
    if OrderStatus(order.status) == OrderStatus.PAID:
        order_service._move(db, order, OrderStatus.PREPARING, actor=None)
    order_service.mark_shipped(db, order)
    order_service.mark_delivered(db, order)
    db.commit()


class TestCallbacks:
    def test_a_signed_callback_holds_the_money(self, db: Session, order: Order) -> None:
        provider, (body, signature) = callback(order)
        payment_service.ingest_callback(
            db, provider_name=provider.name, body=body, signature=signature
        )
        assert PaymentStatus(order.payments[0].status) == PaymentStatus.HELD
        assert OrderStatus(order.status) == OrderStatus.PAID

    def test_a_bad_signature_is_refused_and_changes_nothing(
        self, db: Session, order: Order
    ) -> None:
        provider, (body, _) = callback(order)
        with pytest.raises(Unauthenticated):
            payment_service.ingest_callback(
                db, provider_name=provider.name, body=body, signature="forged"
            )
        assert OrderStatus(order.status) == OrderStatus.AWAITING_PAYMENT

    def test_a_tampered_body_fails_its_signature(self, db: Session, order: Order) -> None:
        provider, (body, signature) = callback(order)
        changed = json.loads(body)
        changed["amount_pkr"] = 1
        with pytest.raises(Unauthenticated):
            payment_service.ingest_callback(
                db,
                provider_name=provider.name,
                body=json.dumps(changed, sort_keys=True).encode(),
                signature=signature,
            )

    def test_a_repeated_callback_is_applied_once(self, db: Session, order: Order) -> None:
        provider, (body, signature) = callback(order)
        for _ in range(2):
            payment_service.ingest_callback(
                db, provider_name=provider.name, body=body, signature=signature
            )
        db.commit()
        assert db.scalar(select(func.count()).select_from(PaymentEvent)) == 1
        paid_events = [e for e in order.events if e.to_status == OrderStatus.PAID]
        assert len(paid_events) == 1

    def test_a_wrong_amount_does_not_count_as_payment(self, db: Session, order: Order) -> None:
        provider, (body, signature) = callback(order, amount=100)
        payment_service.ingest_callback(
            db, provider_name=provider.name, body=body, signature=signature
        )
        assert PaymentStatus(order.payments[0].status) == PaymentStatus.FAILED
        assert "100 PKR" in (order.payments[0].failure_reason or "")
        assert OrderStatus(order.status) == OrderStatus.AWAITING_PAYMENT

    def test_a_failed_payment_can_be_tried_again(self, db: Session, order: Order) -> None:
        payment_service.complete_sandbox_payment(db, order=order, outcome="failed")
        db.commit()
        again = payment_service.ensure_payment(db, order)
        assert PaymentStatus(again.status) == PaymentStatus.PENDING
        assert len(order.payments) == 2

    def test_the_webhook_endpoint_needs_a_signature(self, client: TestClient, order: Order) -> None:
        provider, (body, signature) = callback(order)
        url = f"/payments/webhooks/{provider.name}"
        assert client.post(url, content=body).status_code == 401
        accepted = client.post(url, content=body, headers={"x-sandbox-signature": signature})
        assert accepted.status_code == 200

    def test_sandbox_providers_are_refused_in_production(
        self, order: Order, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("ENVIRONMENT", "production")
        get_settings.cache_clear()
        with pytest.raises(Conflict):
            payment_providers.provider_for(PaymentMethod.JAZZCASH)
        monkeypatch.undo()
        get_settings.cache_clear()


class TestBankTransfer:
    @pytest.fixture
    def bank_order(self, db: Session, buyer: User, lot: Lot) -> Order:
        created = whole_order(db, buyer, lot, method=PaymentMethod.BANK_TRANSFER)
        payment_service.ensure_payment(db, created)
        db.commit()
        return created

    def test_an_admin_confirms_after_the_buyer_gives_a_reference(
        self, db: Session, bank_order: Order, admin_user: User
    ) -> None:
        payment = bank_order.payments[0]
        with pytest.raises(Conflict, match="bank reference"):
            payment_service.confirm_bank_transfer(db, payment=payment, admin=admin_user)

        payment_service.submit_bank_reference(db, order=bank_order, reference="HBL-448812")
        payment_service.confirm_bank_transfer(db, payment=payment, admin=admin_user)
        assert PaymentStatus(payment.status) == PaymentStatus.HELD
        assert OrderStatus(bank_order.status) == OrderStatus.PAID

    def test_one_bank_reference_cannot_pay_two_orders(
        self, db: Session, bank_order: Order, seller, category
    ) -> None:  # type: ignore[no-untyped-def]
        brand, owner = seller
        other_lot = live_lot(db, brand, owner, category.id, offset=30)
        second_buyer = make_reseller(db, phone="03003333333")
        second = whole_order(db, second_buyer, other_lot, method=PaymentMethod.BANK_TRANSFER)
        payment_service.submit_bank_reference(db, order=bank_order, reference="HBL-1")
        db.commit()
        with pytest.raises(Conflict, match="already been used"):
            payment_service.submit_bank_reference(db, order=second, reference="HBL-1")


class TestRelease:
    def test_confirmation_releases_funds_and_records_the_payout(
        self, db: Session, order: Order, buyer: User, seller
    ) -> None:  # type: ignore[no-untyped-def]
        brand, _ = seller
        policy_for(db, brand).payout_terms_days = 5
        db.commit()
        pay(db, order)
        deliver(db, order)
        assert PaymentStatus(order.payments[0].status) == PaymentStatus.HELD

        order_service.confirm_delivery(db, order, actor=buyer)
        db.commit()
        assert PaymentStatus(order.payments[0].status) == PaymentStatus.RELEASED
        payout = db.scalars(select(Payout)).one()
        assert payout.amount_pkr == order.brand_payout_pkr
        assert PayoutStatus(payout.status) == PayoutStatus.PENDING
        assert payout.scheduled_for is not None

    def test_no_payout_exists_before_confirmation(self, db: Session, order: Order) -> None:
        pay(db, order)
        deliver(db, order)
        assert db.scalars(select(Payout)).first() is None

    def test_a_closed_dispute_window_releases_funds(self, db: Session, order: Order) -> None:
        pay(db, order)
        deliver(db, order)
        order_service.close_expired_windows(db, now=utcnow() + timedelta(days=10))
        assert PaymentStatus(order.payments[0].status) == PaymentStatus.RELEASED

    def test_cash_is_held_once_the_courier_delivers(
        self, db: Session, buyer: User, lot: Lot, seller
    ) -> None:  # type: ignore[no-untyped-def]
        brand, _ = seller
        policy_for(db, brand).allow_cod = True
        db.commit()
        cod = whole_order(db, buyer, lot, method=PaymentMethod.COD)
        payment = payment_service.ensure_payment(db, cod)
        db.commit()
        assert PaymentStatus(payment.status) == PaymentStatus.PENDING
        deliver(db, cod)
        assert PaymentStatus(payment.status) == PaymentStatus.HELD

    def test_cancelling_closes_the_unpaid_attempt(
        self, db: Session, order: Order, buyer: User
    ) -> None:
        order_service.cancel(db, order, actor=buyer, reason="Ordered by mistake")
        assert PaymentStatus(order.payments[0].status) == PaymentStatus.FAILED

    def test_money_arriving_after_cancellation_is_flagged(
        self, db: Session, order: Order, buyer: User
    ) -> None:
        provider, (body, signature) = callback(order)
        order_service.cancel(db, order, actor=buyer, reason="Ordered by mistake")
        order.payments[0].status = PaymentStatus.PENDING
        db.commit()
        payment_service.ingest_callback(
            db, provider_name=provider.name, body=body, signature=signature
        )
        db.commit()
        kinds = {item.kind for item in payment_service.reconciliation(db)}
        assert "held_on_closed_order" in kinds


class TestRefundsAndDisputes:
    def _dispute(self, db: Session, order: Order, buyer: User) -> Dispute:
        pay(db, order)
        deliver(db, order)
        dispute = order_service.open_dispute(
            db, order, actor=buyer, reason="Short delivered", detail=None
        )
        db.commit()
        return dispute

    def test_a_full_refund_reverses_the_sale(
        self, db: Session, order: Order, lot: Lot, admin_user: User
    ) -> None:
        pay(db, order)
        payment_service.refund_order(db, order=order, admin=admin_user, note="Brand cannot supply")
        db.commit()
        assert OrderStatus(order.status) == OrderStatus.REFUNDED
        assert order.payments[0].refunded_pkr == order.total_pkr
        assert lot.reserved_pieces == 0
        assert db.scalars(select(Payout)).first() is None

    def test_a_seller_win_pays_the_brand_in_full(
        self, db: Session, order: Order, buyer: User, admin_user: User
    ) -> None:
        dispute = self._dispute(db, order, buyer)
        payment_service.resolve_dispute(
            db,
            dispute=dispute,
            admin=admin_user,
            resolution="The photographs show the full quantity arrived.",
            refund_pkr=0,
        )
        assert DisputeStatus(dispute.status) == DisputeStatus.RESOLVED_SELLER
        assert OrderStatus(order.status) == OrderStatus.CONFIRMED
        assert db.scalars(select(Payout)).one().amount_pkr == order.brand_payout_pkr

    def test_a_partial_refund_reduces_the_payout(
        self, db: Session, order: Order, buyer: User, admin_user: User
    ) -> None:
        dispute = self._dispute(db, order, buyer)
        payment_service.resolve_dispute(
            db,
            dispute=dispute,
            admin=admin_user,
            resolution="Ten pieces were missing from the carton.",
            refund_pkr=3_000,
        )
        assert order.payments[0].refunded_pkr == 3_000
        assert db.scalars(select(Payout)).one().amount_pkr == order.brand_payout_pkr - 3_000

    def test_a_full_refund_through_a_dispute_creates_no_payout(
        self, db: Session, order: Order, buyer: User, admin_user: User
    ) -> None:
        dispute = self._dispute(db, order, buyer)
        payment_service.resolve_dispute(
            db,
            dispute=dispute,
            admin=admin_user,
            resolution="The wrong goods were delivered entirely.",
            refund_pkr=order.total_pkr,
        )
        assert OrderStatus(order.status) == OrderStatus.REFUNDED
        assert db.scalars(select(Payout)).first() is None

    def test_a_refund_cannot_exceed_what_was_paid(
        self, db: Session, order: Order, buyer: User, admin_user: User
    ) -> None:
        dispute = self._dispute(db, order, buyer)
        with pytest.raises(ValidationFailed, match="most that can be refunded"):
            payment_service.resolve_dispute(
                db,
                dispute=dispute,
                admin=admin_user,
                resolution="An attempt to refund too much.",
                refund_pkr=order.total_pkr + 1,
            )

    def test_a_decision_needs_an_explanation(
        self, db: Session, order: Order, buyer: User, admin_user: User
    ) -> None:
        dispute = self._dispute(db, order, buyer)
        with pytest.raises(ValidationFailed, match="Explain"):
            payment_service.resolve_dispute(
                db, dispute=dispute, admin=admin_user, resolution="No", refund_pkr=0
            )


class TestBuyerApi:
    def _create(self, client: TestClient, buyer: User, lot: Lot) -> str:
        response = client.post(
            "/orders",
            json={
                "delivery_city": "Multan",
                "delivery_address": "Shop 12, Hussain Agahi",
                "delivery_phone": "03001234567",
                "payment_method": "easypaisa",
                "purchase": {"lot_id": lot.id},
            },
            headers=auth(buyer),
        )
        assert response.status_code == 201, response.text
        return str(response.json()["id"])

    def test_a_buyer_pays_in_the_sandbox(self, client: TestClient, buyer: User, lot: Lot) -> None:
        order_id = self._create(client, buyer, lot)
        started = client.post(f"/orders/{order_id}/payment", headers=auth(buyer)).json()
        assert started["action"] == "sandbox_wallet"

        paid = client.post(
            f"/orders/{order_id}/payment/sandbox-complete",
            json={"outcome": "succeeded"},
            headers=auth(buyer),
        ).json()
        assert paid["status"] == "held"
        detail = client.get(f"/orders/{order_id}", headers=auth(buyer)).json()
        assert detail["status"] == "paid"

    def test_only_the_buyer_can_pay(
        self, client: TestClient, db: Session, buyer: User, lot: Lot
    ) -> None:
        order_id = self._create(client, buyer, lot)
        stranger = make_reseller(db, phone="03002222233")
        response = client.post(f"/orders/{order_id}/payment", headers=auth(stranger))
        assert response.status_code == 404
