"""The admin panel, and the whole Phase 3 journey through the API."""

from __future__ import annotations

from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from catalog_helpers import jpeg_bytes
from commerce_helpers import (
    BASE_LOT_JSON,
    DELIVERY_JSON,
    auth,
    live_lot,
    make_courier,
    make_reseller,
    whole_order,
)
from khazana.core.errors import Conflict, ValidationFailed
from khazana.models import AuditLog, Brand, Lot, Order, Payout, User
from khazana.models.base import utcnow
from khazana.models.enums import (
    LotStatus,
    OrderStatus,
    PaymentMethod,
    PayoutStatus,
    PhotoKind,
    VerificationStatus,
)
from khazana.services import (
    admin_service,
    logistics_service,
    order_service,
    payment_service,
)


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


def confirmed_order(db: Session, buyer: User, lot: Lot, owner: User) -> Order:
    order = whole_order(db, buyer, lot)
    payment_service.complete_sandbox_payment(db, order=order, outcome="succeeded")
    shipment = logistics_service.book_shipment(db, order=order, actor=owner)
    for _ in range(3):
        logistics_service.advance_sandbox(db, shipment=shipment)
    order_service.confirm_delivery(db, order, actor=buyer)
    db.commit()
    return order


class TestAccess:
    @pytest.mark.parametrize(
        "path",
        [
            "/admin/overview",
            "/admin/resellers",
            "/admin/brands",
            "/admin/listings",
            "/admin/payments",
            "/admin/reconciliation",
            "/admin/disputes",
            "/admin/payouts",
            "/admin/payout-runs",
            "/admin/couriers",
            "/admin/audit",
        ],
    )
    def test_only_admins_get_in(
        self, client: TestClient, buyer: User, seller, admin_user: User, path: str
    ) -> None:  # type: ignore[no-untyped-def]
        _, owner = seller
        assert client.get(path).status_code == 401
        assert client.get(path, headers=auth(buyer)).status_code == 403
        assert client.get(path, headers=auth(owner)).status_code == 403
        assert client.get(path, headers=auth(admin_user)).status_code == 200


class TestVerification:
    def test_a_new_reseller_is_verified_by_an_admin(
        self, client: TestClient, db: Session, admin_user: User
    ) -> None:
        user = User(phone="03009000001", full_name="New Shop", role=auth_role())
        db.add(user)
        db.commit()
        saved = client.put(
            "/resellers/me",
            json={"business_name": "New Shop", "city": "Lahore"},
            headers=auth(user),
        )
        assert saved.status_code == 200, saved.text
        assert saved.json()["status"] == "pending"

        queue = client.get("/admin/resellers", headers=auth(admin_user)).json()
        assert [row["business_name"] for row in queue] == ["New Shop"]

        decided = client.post(
            f"/admin/resellers/{queue[0]['id']}/review",
            json={"approve": True},
            headers=auth(admin_user),
        )
        assert decided.json()["status"] == "verified"

    def test_renaming_a_verified_business_needs_a_new_check(
        self, client: TestClient, buyer: User
    ) -> None:
        response = client.put(
            "/resellers/me",
            json={"business_name": "Another Name", "city": "Multan"},
            headers=auth(buyer),
        )
        assert response.json()["status"] == "pending"

    def test_a_rejection_needs_a_reason(self, db: Session, admin_user: User) -> None:
        user = make_reseller(db, phone="03009000002", status=VerificationStatus.PENDING)
        assert user.reseller_profile is not None
        with pytest.raises(ValidationFailed, match="needs to fix"):
            admin_service.review_reseller(
                db,
                profile_id=user.reseller_profile.id,
                admin=admin_user,
                approve=False,
                note="no",
            )


class TestCommercialTerms:
    def test_a_rate_change_does_not_touch_existing_orders(
        self, client: TestClient, db: Session, buyer: User, lot: Lot, seller, admin_user: User
    ) -> None:  # type: ignore[no-untyped-def]
        brand, _ = seller
        order = whole_order(db, buyer, lot)
        response = client.patch(
            f"/admin/brands/{brand.id}/terms",
            json={"commission_percent": 9},
            headers=auth(admin_user),
        )
        assert response.status_code == 200, response.text
        assert response.json()["policy"]["commission_percent"] == 9
        db.refresh(order)
        assert float(order.commission_percent) == 15


class TestModeration:
    def test_the_risk_score_is_shown_and_a_listing_can_be_taken_down(
        self, client: TestClient, lot: Lot, seller, admin_user: User
    ) -> None:  # type: ignore[no-untyped-def]
        brand, _ = seller
        rows = client.get("/admin/listings", headers=auth(admin_user)).json()
        assert rows[0]["brand_name"] == brand.name
        assert "risk_score" in rows[0]

        response = client.post(
            f"/admin/listings/{lot.id}/take-down",
            json={"note": "Reported as counterfeit stock"},
            headers=auth(admin_user),
        )
        assert response.status_code == 200, response.text
        assert response.json()["status"] == LotStatus.PAUSED.value


class TestPayoutRuns:
    def test_a_run_gathers_due_payouts_and_is_marked_paid(
        self, db: Session, buyer: User, lot: Lot, seller, admin_user: User
    ) -> None:  # type: ignore[no-untyped-def]
        _, owner = seller
        order = confirmed_order(db, buyer, lot, owner)
        payout = db.scalars(select(Payout)).one()

        with pytest.raises(Conflict, match="No payouts are due"):
            admin_service.create_payout_run(db, admin=admin_user)

        payout.scheduled_for = utcnow() - timedelta(hours=1)
        db.commit()
        run = admin_service.create_payout_run(db, admin=admin_user)
        assert run.total_pkr == order.brand_payout_pkr
        assert PayoutStatus(payout.status) == PayoutStatus.SCHEDULED

        admin_service.mark_run_paid(db, run_id=run.id, admin=admin_user, reference="BATCH-1")
        assert PayoutStatus(payout.status) == PayoutStatus.PAID
        assert payout.reference == "BATCH-1"
        with pytest.raises(Conflict, match="already been completed"):
            admin_service.mark_run_paid(db, run_id=run.id, admin=admin_user, reference="BATCH-2")


class TestShippingConfiguration:
    def test_a_new_rate_changes_the_price_buyers_see(
        self, client: TestClient, db: Session, courier, buyer: User, lot: Lot, admin_user: User
    ) -> None:  # type: ignore[no-untyped-def]
        created = client.post(
            f"/admin/couriers/{courier.id}/rates",
            json={"destination_city": "Multan", "base_pkr": 100, "per_kg_pkr": 10},
            headers=auth(admin_user),
        )
        assert created.status_code == 201, created.text
        db.expire_all()
        assert whole_order(db, buyer, lot).shipping_pkr == 400


def auth_role():  # type: ignore[no-untyped-def]
    from khazana.models.enums import UserRole

    return UserRole.RESELLER


class TestPhaseThreeJourney:
    """The roadmap's exit test, through the public API."""

    def test_from_listing_to_a_paid_out_brand(
        self,
        client: TestClient,
        db: Session,
        buyer: User,
        seller,
        category,
        admin_user: User,
    ) -> None:  # type: ignore[no-untyped-def]
        brand, owner = seller
        owner_headers = auth(owner)
        buyer_headers = auth(buyer)
        admin_headers = auth(admin_user)

        # The brand lists a lot and approves it.
        created = client.post(
            "/lots",
            json={**BASE_LOT_JSON, "brand_id": brand.id, "category_id": category.id},
            headers=owner_headers,
        )
        assert created.status_code == 201, created.text
        lot_id = created.json()["id"]
        client.put(
            f"/lots/{lot_id}/manifest",
            json={"lines": [{"size": "M", "color": "blue", "pieces": 100}]},
            headers=owner_headers,
        ).raise_for_status()
        for index, kind in enumerate((PhotoKind.FULL_LOT, PhotoKind.FRONT, PhotoKind.LABEL)):
            client.post(
                f"/lots/{lot_id}/photos",
                data={"kind": kind.value},
                files={"file": ("p.jpg", jpeg_bytes(seed=index + 1), "image/jpeg")},
                headers=owner_headers,
            ).raise_for_status()
        client.post(f"/lots/{lot_id}/submit", headers=owner_headers).raise_for_status()
        client.post(
            f"/lots/{lot_id}/approve",
            json={"visibility": "public"},
            headers=owner_headers,
        ).raise_for_status()

        # The buyer finds it and sees its photographs.
        found = client.get("/catalog/search", params={"q": "lawn"}, headers=buyer_headers).json()
        assert found["items"][0]["lot"]["id"] == lot_id
        cover = found["items"][0]["cover_photo_id"]
        image = client.get(f"/catalog/{lot_id}/photos/{cover}", headers=buyer_headers)
        assert image.status_code == 200

        # Cart, checkout and sandbox payment.
        client.put(f"/cart/items/{lot_id}", json={}, headers=buyer_headers).raise_for_status()
        orders = client.post(
            "/cart/checkout",
            json={**DELIVERY_JSON, "payment_method": PaymentMethod.JAZZCASH.value},
            headers=buyer_headers,
        )
        assert orders.status_code == 201, orders.text
        order_id = orders.json()[0]["id"]
        client.post(
            f"/orders/{order_id}/payment/sandbox-complete",
            json={"outcome": "succeeded"},
            headers=buyer_headers,
        ).raise_for_status()

        # The brand ships it and the courier delivers.
        shipment = client.post(f"/orders/{order_id}/shipments", headers=owner_headers).json()
        for _ in range(3):
            client.post(
                f"/shipments/{shipment['id']}/sandbox-advance", headers=owner_headers
            ).raise_for_status()
        tracking = client.get(f"/orders/{order_id}/tracking", headers=buyer_headers).json()
        assert tracking[0]["status"] == "delivered"

        # The buyer confirms, which releases the money.
        confirmed = client.post(f"/orders/{order_id}/confirm", headers=buyer_headers).json()
        assert confirmed["status"] == OrderStatus.CONFIRMED.value

        # The admin sees it and pays the brand.
        admin_order = client.get(f"/orders/{order_id}", headers=admin_headers).json()
        assert admin_order["commission_pkr"] == 4_500
        payout = db.scalars(select(Payout)).one()
        payout.scheduled_for = utcnow() - timedelta(minutes=1)
        db.commit()
        run = client.post("/admin/payout-runs", json={}, headers=admin_headers)
        assert run.status_code == 201, run.text
        client.post(
            f"/admin/payout-runs/{run.json()['id']}/paid",
            json={"reference": "BATCH-77"},
            headers=admin_headers,
        ).raise_for_status()

        paid = client.get("/payouts", headers=owner_headers).json()
        assert paid[0]["status"] == "paid"
        assert client.get("/admin/reconciliation", headers=admin_headers).json() == []
        assert db.scalars(select(AuditLog).where(AuditLog.action == "payout_run.paid")).first()
