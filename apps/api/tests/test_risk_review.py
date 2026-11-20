"""Fraud and counterfeit review: signals open cases, and only people decide."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from commerce_helpers import auth, live_lot, make_courier, make_reseller, whole_order
from khazana.core.errors import Conflict, ValidationFailed
from khazana.models import AuditLog, ReviewCase
from khazana.models.enums import (
    LotStatus,
    OrderStatus,
    PaymentMethod,
    ReviewStatus,
    VerificationStatus,
)
from khazana.services import risk_service


def _case(db: Session, subject_type: str, subject_id: str) -> ReviewCase | None:
    return db.scalar(
        select(ReviewCase).where(
            ReviewCase.subject_type == subject_type, ReviewCase.subject_id == subject_id
        )
    )


class TestSignals:
    def test_a_listing_naming_another_brand_opens_a_case(
        self,
        db: Session,
        two_brands,
        category,  # type: ignore[no-untyped-def]
    ) -> None:
        (one, owner), (two, _) = two_brands
        lot = live_lot(db, one, owner, category.id, title=f"Original {two.name} lawn suits")
        risk_service.run(db)
        case = _case(db, "listing", lot.id)
        assert case is not None and case.status == ReviewStatus.OPEN
        codes = [s["code"] for s in case.signals["signals"]]
        assert "names_another_brand" in codes

    def test_an_ordinary_listing_opens_nothing(
        self,
        db: Session,
        two_brands,
        category,  # type: ignore[no-untyped-def]
    ) -> None:
        (one, owner), _ = two_brands
        lot = live_lot(db, one, owner, category.id)
        risk_service.run(db)
        assert _case(db, "listing", lot.id) is None

    def test_cod_refusals_and_a_shared_number_flag_an_account(
        self,
        db: Session,
        two_brands,
        category,  # type: ignore[no-untyped-def]
    ) -> None:
        (one, owner), _ = two_brands
        make_courier(db)
        buyers = [make_reseller(db, phone=f"0300700000{n}") for n in range(3)]
        for n, buyer in enumerate(buyers):
            lot = live_lot(db, one, owner, category.id, offset=n)
            order = whole_order(db, buyer, lot)
            order.delivery_phone = "03001112222"
            if n == 0:
                order.payment_method = PaymentMethod.COD
                order.status = OrderStatus.CANCELLED
        extra = live_lot(db, one, owner, category.id, offset=9)
        second = whole_order(db, buyers[0], extra)
        second.payment_method = PaymentMethod.COD
        second.status = OrderStatus.CANCELLED
        db.commit()

        risk_service.run(db)
        case = _case(db, "account", buyers[0].id)
        assert case is not None
        codes = {s["code"] for s in case.signals["signals"]}
        assert {"cod_refusals", "shared_phone"} <= codes
        assert case.score == 55


class TestDecisions:
    @pytest.fixture
    def listing_case(self, db: Session, two_brands, category):  # type: ignore[no-untyped-def]
        (one, owner), (two, _) = two_brands
        lot = live_lot(db, one, owner, category.id, title=f"{two.name} copy suits")
        risk_service.run(db)
        case = _case(db, "listing", lot.id)
        assert case is not None
        return case, lot

    def test_a_person_pauses_the_listing_and_it_is_audited(
        self,
        db: Session,
        listing_case,
        admin_user,  # type: ignore[no-untyped-def]
    ) -> None:
        case, lot = listing_case
        risk_service.decide(
            db,
            case_id=case.id,
            admin=admin_user,
            outcome=ReviewStatus.ACTIONED,
            action="pause_listing",
            note="Uses another brand's name.",
        )
        assert lot.status == LotStatus.PAUSED
        assert db.scalar(select(AuditLog).where(AuditLog.action == "review_case.actioned"))

    def test_scoring_never_acts_by_itself(self, db: Session, listing_case) -> None:  # type: ignore[no-untyped-def]
        _, lot = listing_case
        risk_service.run(db)
        assert lot.status == LotStatus.LIVE

    def test_a_decision_needs_a_note_and_a_sensible_action(
        self,
        db: Session,
        listing_case,
        admin_user,  # type: ignore[no-untyped-def]
    ) -> None:
        case, _ = listing_case
        with pytest.raises(ValidationFailed, match="note"):
            risk_service.decide(
                db,
                case_id=case.id,
                admin=admin_user,
                outcome=ReviewStatus.CLEARED,
                action="none",
                note=" ",
            )
        with pytest.raises(ValidationFailed, match="Only an account"):
            risk_service.decide(
                db,
                case_id=case.id,
                admin=admin_user,
                outcome=ReviewStatus.ACTIONED,
                action="suspend_account",
                note="wrong action",
            )

    def test_a_decided_case_is_not_reopened_by_the_same_evidence(
        self,
        db: Session,
        listing_case,
        admin_user,  # type: ignore[no-untyped-def]
    ) -> None:
        case, _ = listing_case
        risk_service.decide(
            db,
            case_id=case.id,
            admin=admin_user,
            outcome=ReviewStatus.CLEARED,
            action="none",
            note="Licensed.",
        )
        risk_service.run(db)
        assert case.status == ReviewStatus.CLEARED
        with pytest.raises(Conflict):
            risk_service.decide(
                db,
                case_id=case.id,
                admin=admin_user,
                outcome=ReviewStatus.CLEARED,
                action="none",
                note="again",
            )

    def test_suspending_an_account(
        self,
        db: Session,
        two_brands,
        admin_user,  # type: ignore[no-untyped-def]
    ) -> None:
        buyer = make_reseller(db)
        case = ReviewCase(
            subject_type="account",
            subject_id=buyer.id,
            score=60,
            signals={"signals": []},
            scored_at=datetime.now(UTC) - timedelta(hours=1),
        )
        db.add(case)
        db.commit()
        risk_service.decide(
            db,
            case_id=case.id,
            admin=admin_user,
            outcome=ReviewStatus.ACTIONED,
            action="suspend_account",
            note="Repeated refused deliveries.",
        )
        assert buyer.reseller_profile.status == VerificationStatus.SUSPENDED


class TestEndpoints:
    def test_the_queue_is_for_admins_only(
        self,
        client: TestClient,
        db: Session,
        two_brands,
        admin_user,  # type: ignore[no-untyped-def]
    ) -> None:
        (_, owner), _ = two_brands
        assert client.get("/admin/review-cases", headers=auth(owner)).status_code == 403
        ran = client.post("/admin/jobs/risk", headers=auth(admin_user))
        assert ran.status_code == 200, ran.text
        assert client.get("/admin/review-cases", headers=auth(admin_user)).status_code == 200

    def test_a_case_names_its_subject(
        self,
        client: TestClient,
        db: Session,
        two_brands,
        category,
        admin_user,  # type: ignore[no-untyped-def]
    ) -> None:
        (one, owner), (two, _) = two_brands
        lot = live_lot(db, one, owner, category.id, title=f"{two.name} copy suits")
        risk_service.run(db)
        db.commit()
        [case] = client.get("/admin/review-cases", headers=auth(admin_user)).json()
        assert case["subject_label"].startswith(lot.lot_code)
        assert case["subject_link"] == "/admin/listings"
