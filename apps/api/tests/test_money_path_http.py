"""The money path end to end, over HTTP only.

Every other money test calls a service directly. This one does what the
three people involved actually do, through the API and nothing else: the
reseller orders and pays, the brand books the courier, the courier reports
delivery, the buyer confirms, the admin pays the brand. At each step it checks
where every rupee is: what the buyer was charged, what the platform keeps and
what the brand is paid must add up, and nobody can take a step that belongs
to someone else.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from commerce_helpers import DELIVERY_JSON, auth, live_lot, make_courier, make_reseller, policy_for
from khazana.models import Lot, Order, Payment, Payout, PayoutRun
from khazana.models.enums import OrderStatus, PaymentStatus, PayoutStatus


@pytest.fixture
def market(db: Session, two_brands, category, admin_user):  # type: ignore[no-untyped-def]
    (brand, owner), (_, other_owner) = two_brands
    make_courier(db)
    policy = policy_for(db, brand)
    policy.commission_percent = Decimal(15)
    policy.payout_terms_days = 0
    db.commit()
    lot = live_lot(db, brand, owner, category.id)
    buyer = make_reseller(db)
    stranger = make_reseller(db, phone="03008888881")
    return {
        "brand": brand,
        "owner": owner,
        "other_owner": other_owner,
        "lot": lot,
        "buyer": buyer,
        "stranger": stranger,
        "admin": admin_user,
    }


def _ok(response, code: int = 200):  # type: ignore[no-untyped-def]
    assert response.status_code == code, response.text
    return response.json()


def test_an_order_travels_from_checkout_to_brand_payout(
    client: TestClient, db: Session, market
) -> None:  # type: ignore[no-untyped-def]
    lot: Lot = market["lot"]
    buyer, owner, admin = market["buyer"], market["owner"], market["admin"]
    pieces_before = lot.available_pieces

    # 1. The reseller orders the whole lot. Stock is reserved at once.
    purchase = {"lot_id": lot.id, "whole_lot": True}
    created = _ok(
        client.post(
            "/orders",
            json={**DELIVERY_JSON, "payment_method": "jazzcash", "purchase": purchase},
            headers=auth(buyer),
        ),
        201,
    )
    order_id = created["id"]
    order = db.get(Order, order_id)
    assert order is not None
    assert order.total_pkr == order.subtotal_pkr + order.shipping_pkr
    assert order.brand_payout_pkr + order.commission_pkr == order.subtotal_pkr
    assert order.commission_pkr == round(order.subtotal_pkr * 15 / 100)
    db.refresh(lot)
    assert lot.available_pieces == pieces_before - order.pieces

    # 2. Nobody else can pay for, see or ship this order.
    for intruder in (market["stranger"], market["other_owner"]):
        assert client.get(f"/orders/{order_id}", headers=auth(intruder)).status_code in (403, 404)
        assert client.post(f"/orders/{order_id}/payment", headers=auth(intruder)).status_code in (
            403,
            404,
        )
    assert client.post(f"/orders/{order_id}/shipments", headers=auth(owner)).status_code in (
        400,
        409,
    ), "an unpaid prepaid order cannot be shipped"

    # 3. The buyer pays the exact total through the sandbox provider.
    _ok(client.post(f"/orders/{order_id}/payment", headers=auth(buyer)))
    paid = _ok(
        client.post(
            f"/orders/{order_id}/payment/sandbox-complete",
            json={"outcome": "succeeded"},
            headers=auth(buyer),
        )
    )
    assert paid["status"] == PaymentStatus.HELD.value
    detail = _ok(client.get(f"/orders/{order_id}", headers=auth(buyer)))
    assert detail["status"] == OrderStatus.PAID.value
    payment = db.scalars(select(Payment).where(Payment.order_id == order_id)).one()
    assert payment.amount_pkr == order.total_pkr
    assert PaymentStatus(payment.status) == PaymentStatus.HELD

    # 4. The brand books the courier and the courier reports each step.
    _ok(client.post(f"/orders/{order_id}/prepare", headers=auth(owner)))
    booked = _ok(client.post(f"/orders/{order_id}/shipments", headers=auth(owner)), 201)
    shipment_id = booked["id"]
    for _ in range(3):
        _ok(client.post(f"/shipments/{shipment_id}/sandbox-advance", headers=auth(owner)))
    db.expire_all()
    assert OrderStatus(db.get(Order, order_id).status) == OrderStatus.DELIVERED  # type: ignore[union-attr]
    assert db.scalars(select(Payout)).first() is None, "no payout before the buyer confirms"

    # 5. Only the buyer can confirm, and confirming releases the money.
    assert client.post(f"/orders/{order_id}/confirm", headers=auth(owner)).status_code in (403, 404)
    _ok(client.post(f"/orders/{order_id}/confirm", headers=auth(buyer)))
    db.expire_all()
    payout = db.scalars(select(Payout)).one()
    assert payout.amount_pkr == order.brand_payout_pkr
    assert PaymentStatus(db.get(Payment, payment.id).status) == PaymentStatus.RELEASED  # type: ignore[union-attr]

    # 6. The brand sees the payout; only an admin can send it.
    brand_view = _ok(client.get("/payouts", headers=auth(owner)))
    assert any(row["amount_pkr"] == order.brand_payout_pkr for row in _rows(brand_view))
    assert client.post("/admin/payout-runs", json={}, headers=auth(owner)).status_code == 403
    run = _ok(client.post("/admin/payout-runs", json={}, headers=auth(admin)), 201)
    assert run["total_pkr"] == order.brand_payout_pkr
    sent = _ok(
        client.post(
            f"/admin/payout-runs/{run['id']}/paid",
            json={"reference": "IBFT-0001"},
            headers=auth(admin),
        )
    )
    assert sent["status"] == PayoutStatus.PAID.value
    db.expire_all()
    assert PayoutStatus(db.get(Payout, payout.id).status) == PayoutStatus.PAID  # type: ignore[union-attr]
    assert db.get(PayoutRun, run["id"]).total_pkr == payout.amount_pkr  # type: ignore[union-attr]

    # 7. The same payout cannot be sent twice.
    assert client.post("/admin/payout-runs", json={}, headers=auth(admin)).status_code == 409


def _rows(body):  # type: ignore[no-untyped-def]
    if isinstance(body, list):
        return body
    for key in ("items", "payouts", "rows"):
        if key in body:
            return body[key]
    raise AssertionError(f"unexpected payouts shape: {list(body)}")
