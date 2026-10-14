"""The brand portal.

Verification is the first consequential action in the platform, so the tests
here are mostly about who is allowed to do what, and whether the audit trail
actually records it.
"""

from __future__ import annotations

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from khazana.core.errors import Conflict, Forbidden, NotFound, ValidationFailed
from khazana.models import AuditLog, Brand, BrandPolicy, Category, Lot, User
from khazana.models.enums import (
    ConditionGrade,
    DocumentType,
    LotStatus,
    UserRole,
    VerificationStatus,
    Visibility,
)
from khazana.services import audit_service, brand_service


def png() -> bytes:
    import io

    from PIL import Image

    buffer = io.BytesIO()
    Image.new("RGB", (40, 40), (10, 20, 30)).save(buffer, format="PNG")
    return buffer.getvalue()


@pytest.fixture
def owner(db: Session) -> User:
    user = User(phone="03001234567", full_name="Brand Owner", role=UserRole.RESELLER)
    db.add(user)
    db.commit()
    return user


@pytest.fixture
def admin(db: Session) -> User:
    user = User(phone="03009999999", full_name="Admin", role=UserRole.ADMIN)
    db.add(user)
    db.commit()
    return user


def register(db: Session, owner: User, name: str = "Meher Textiles") -> Brand:
    brand = brand_service.register_brand(db, owner=owner, name=name, city="Lahore")
    db.commit()
    return brand


def supply_required_documents(db: Session, brand: Brand, owner: User) -> None:
    for doc in brand_service.REQUIRED_DOCUMENTS:
        brand_service.upload_document(
            db,
            brand_id=brand.id,
            doc_type=doc,
            data=png(),
            filename=f"{doc.value}.png",
            content_type="image/png",
            uploaded_by=owner,
        )
    db.commit()


class TestRegistration:
    def test_registering_creates_the_policy_and_the_membership(
        self, db: Session, owner: User
    ) -> None:
        """A brand without a policy row has no commission rate or discount band.

        Creating it lazily would leave the brand unpriceable rather than
        merely incomplete, so it is created here.
        """
        brand = register(db, owner)

        policy = db.scalars(select(BrandPolicy).where(BrandPolicy.brand_id == brand.id)).one()
        assert policy.commission_percent == 15
        assert policy.require_brand_approval is True

        assert brand.slug == "meher-textiles"
        assert brand.status == VerificationStatus.PENDING
        assert brand.id in [m.brand_id for m in owner.brand_memberships]

    def test_the_registrant_becomes_a_brand_user(self, db: Session, owner: User) -> None:
        """Otherwise they register a brand and then cannot see it."""
        assert owner.role == UserRole.RESELLER
        register(db, owner)
        assert owner.role == UserRole.BRAND

    def test_a_duplicate_web_address_is_refused_clearly(self, db: Session, owner: User) -> None:
        register(db, owner, name="Meher Textiles")

        second = User(phone="03002222222", full_name="Other", role=UserRole.RESELLER)
        db.add(second)
        db.commit()

        with pytest.raises(Conflict, match="already exists"):
            brand_service.register_brand(
                db, owner=second, name="  meher   textiles ", city="Karachi"
            )

    def test_an_unusable_name_is_refused(self, db: Session, owner: User) -> None:
        with pytest.raises(ValidationFailed):
            brand_service.register_brand(db, owner=owner, name="!!!", city="Lahore")

    def test_registration_is_audited(self, db: Session, owner: User) -> None:
        brand = register(db, owner)

        entry = db.scalars(select(AuditLog).where(AuditLog.action == "brand.registered")).one()
        assert entry.entity_id == brand.id
        assert entry.actor_user_id == owner.id
        assert entry.after["name"] == "Meher Textiles"


class TestDocuments:
    def test_uploading_stores_the_file_and_records_it(
        self, db: Session, owner: User, local_storage
    ) -> None:
        brand = register(db, owner)

        doc = brand_service.upload_document(
            db,
            brand_id=brand.id,
            doc_type=DocumentType.NTN,
            data=png(),
            filename="ntn.png",
            content_type="image/png",
            uploaded_by=owner,
        )
        db.commit()

        assert doc.status == VerificationStatus.PENDING
        assert doc.file_key.startswith(f"verification/{brand.id}/")
        assert doc.size_bytes > 0

        from khazana.storage import read_object

        assert read_object(doc.file_key) == png()

    def test_a_file_that_is_not_what_it_claims_is_refused(
        self, db: Session, owner: User, local_storage
    ) -> None:
        brand = register(db, owner)

        with pytest.raises(ValidationFailed):
            brand_service.upload_document(
                db,
                brand_id=brand.id,
                doc_type=DocumentType.NTN,
                data=b"<html>not an image</html>",
                filename="ntn.png",
                content_type="image/png",
                uploaded_by=owner,
            )

    def test_replacing_a_document_resets_its_review(
        self, db: Session, owner: User, admin: User, local_storage
    ) -> None:
        """An admin who approved the old file has not seen the new one."""
        brand = register(db, owner)
        doc = brand_service.upload_document(
            db,
            brand_id=brand.id,
            doc_type=DocumentType.NTN,
            data=png(),
            filename="ntn.png",
            content_type="image/png",
            uploaded_by=owner,
        )
        doc.status = VerificationStatus.VERIFIED
        doc.reviewed_by_user_id = admin.id
        db.commit()

        replaced = brand_service.upload_document(
            db,
            brand_id=brand.id,
            doc_type=DocumentType.NTN,
            data=png(),
            filename="ntn-v2.png",
            content_type="image/png",
            uploaded_by=owner,
        )
        db.commit()

        assert replaced.id == doc.id
        assert replaced.status == VerificationStatus.PENDING
        assert replaced.reviewed_by_user_id is None

    def test_missing_documents_are_listed(self, db: Session, owner: User, local_storage) -> None:
        brand = register(db, owner)
        assert brand_service.missing_documents(db, brand.id) == list(
            brand_service.REQUIRED_DOCUMENTS
        )

        brand_service.upload_document(
            db,
            brand_id=brand.id,
            doc_type=DocumentType.NTN,
            data=png(),
            filename="ntn.png",
            content_type="image/png",
            uploaded_by=owner,
        )
        db.commit()

        assert brand_service.missing_documents(db, brand.id) == [DocumentType.INCORPORATION]


class TestVerification:
    def test_verification_cannot_be_requested_with_documents_missing(
        self, db: Session, owner: User
    ) -> None:
        """An incomplete application in the queue wastes the admin's time."""
        brand = register(db, owner)

        with pytest.raises(ValidationFailed, match="Upload these documents first"):
            brand_service.request_verification(db, brand_id=brand.id, requested_by=owner)

    def test_a_brand_cannot_verify_itself(self, db: Session, owner: User, local_storage) -> None:
        """A brand that could verify itself is not verification."""
        brand = register(db, owner)
        supply_required_documents(db, brand, owner)

        with pytest.raises(Forbidden, match="Only an admin"):
            brand_service.review_brand(db, brand_id=brand.id, admin=owner, approve=True)

    def test_an_admin_verifies_and_the_documents_follow(
        self, db: Session, owner: User, admin: User, local_storage
    ) -> None:
        brand = register(db, owner)
        supply_required_documents(db, brand, owner)
        brand_service.request_verification(db, brand_id=brand.id, requested_by=owner)
        db.commit()

        brand_service.review_brand(db, brand_id=brand.id, admin=admin, approve=True)
        db.commit()

        assert brand.status == VerificationStatus.VERIFIED
        assert brand.reviewed_by_user_id == admin.id
        assert brand.reviewed_at is not None

        from khazana.models import VerificationDocument

        docs = db.scalars(
            select(VerificationDocument).where(VerificationDocument.brand_id == brand.id)
        ).all()
        assert all(doc.status == VerificationStatus.VERIFIED for doc in docs)

    def test_approval_is_refused_while_documents_are_missing(
        self, db: Session, owner: User, admin: User
    ) -> None:
        brand = register(db, owner)

        with pytest.raises(ValidationFailed, match="required documents"):
            brand_service.review_brand(db, brand_id=brand.id, admin=admin, approve=True)

    def test_a_rejection_must_carry_a_reason(self, db: Session, owner: User, admin: User) -> None:
        """A brand told only "rejected" cannot fix anything."""
        brand = register(db, owner)

        with pytest.raises(ValidationFailed, match="reason"):
            brand_service.review_brand(db, brand_id=brand.id, admin=admin, approve=False)

        brand_service.review_brand(
            db,
            brand_id=brand.id,
            admin=admin,
            approve=False,
            note="The NTN certificate is unreadable.",
        )
        db.commit()

        assert brand.status == VerificationStatus.REJECTED
        assert "unreadable" in brand.review_note

    def test_the_decision_is_audited_with_before_and_after(
        self, db: Session, owner: User, admin: User, local_storage
    ) -> None:
        brand = register(db, owner)
        supply_required_documents(db, brand, owner)
        brand_service.review_brand(db, brand_id=brand.id, admin=admin, approve=True)
        db.commit()

        entry = db.scalars(select(AuditLog).where(AuditLog.action == "brand.verified")).one()
        assert entry.actor_user_id == admin.id
        assert entry.actor_role == "admin"
        assert entry.before["status"] == "pending"
        assert entry.after["status"] == "verified"


class TestSuspension:
    def test_suspending_takes_live_listings_down(
        self, db: Session, owner: User, admin: User
    ) -> None:
        """Leaving them up lets a suspended brand keep taking orders."""
        brand = register(db, owner)
        category = Category(name="Womenswear", slug="womenswear")
        db.add(category)
        db.flush()

        lot = Lot(
            lot_code="LOT-1",
            brand_id=brand.id,
            category_id=category.id,
            title="Lawn suits",
            condition_grade=ConditionGrade.A,
            total_pieces=10,
            retail_price_per_piece_pkr=1000,
            lot_price_pkr=3000,
            min_order_pieces=10,
            stock_city="Lahore",
            status=LotStatus.LIVE,
            visibility=Visibility.PUBLIC,
            approved_at=__import__("khazana.models.base", fromlist=["utcnow"]).utcnow(),
        )
        db.add(lot)
        db.commit()

        brand_service.suspend_brand(
            db, brand_id=brand.id, admin=admin, reason="Counterfeit report under review"
        )
        db.commit()

        assert brand.status == VerificationStatus.SUSPENDED
        assert lot.status == LotStatus.PAUSED

    def test_only_an_admin_can_suspend(self, db: Session, owner: User) -> None:
        brand = register(db, owner)
        with pytest.raises(Forbidden):
            brand_service.suspend_brand(db, brand_id=brand.id, admin=owner, reason="because")


class TestPolicy:
    def test_a_brand_sets_its_own_commercial_terms(self, db: Session, owner: User) -> None:
        """Policy is data. This is the whole point of that rule."""
        brand = register(db, owner)

        policy = brand_service.update_policy(
            db,
            brand_id=brand.id,
            actor=owner,
            changes={"commission_percent": 12, "payout_terms_days": 3, "allow_cod": True},
        )
        db.commit()

        assert policy.commission_percent == 12
        assert policy.payout_terms_days == 3
        assert policy.allow_cod is True

    def test_the_approval_gate_cannot_be_switched_off(self, db: Session, owner: User) -> None:
        """Pinned in the schema, and refused here with an explanation.

        Offering it as an editable field would promise something the database
        will refuse, so it is rejected before it reaches the constraint.
        """
        brand = register(db, owner)

        with pytest.raises(ValidationFailed, match="not optional"):
            brand_service.update_policy(
                db,
                brand_id=brand.id,
                actor=owner,
                changes={"require_brand_approval": False},
            )

    def test_an_unknown_setting_is_refused(self, db: Session, owner: User) -> None:
        brand = register(db, owner)
        with pytest.raises(ValidationFailed, match="cannot be changed"):
            brand_service.update_policy(
                db, brand_id=brand.id, actor=owner, changes={"status": "verified"}
            )

    def test_an_inverted_discount_band_is_caught_before_the_database(
        self, db: Session, owner: User
    ) -> None:
        """The brand gets a sentence rather than a constraint violation."""
        brand = register(db, owner)

        with pytest.raises(ValidationFailed, match="must be below"):
            brand_service.update_policy(
                db,
                brand_id=brand.id,
                actor=owner,
                changes={"min_discount_percent": 90, "max_discount_percent": 40},
            )

    def test_only_the_changed_fields_are_audited(self, db: Session, owner: User) -> None:
        """A log that stores the whole object twice makes a reader hunt."""
        brand = register(db, owner)
        brand_service.update_policy(
            db, brand_id=brand.id, actor=owner, changes={"commission_percent": 11}
        )
        db.commit()

        entry = db.scalars(select(AuditLog).where(AuditLog.action == "brand.policy_updated")).one()
        assert set(entry.after) == {"commission_percent"}
        assert entry.after["commission_percent"] == {"from": "15.00", "to": "11.00"}

    def test_setting_a_value_to_what_it_already_was_logs_no_change(
        self, db: Session, owner: User
    ) -> None:
        """The reason the snapshot is taken after a refresh.

        Without it the previous value comes back from the database as a
        Decimal while the new one is still the integer that was typed, and the
        diff reports a change that never happened.
        """
        brand = register(db, owner)
        brand_service.update_policy(
            db, brand_id=brand.id, actor=owner, changes={"commission_percent": 15}
        )
        db.commit()

        entry = db.scalars(select(AuditLog).where(AuditLog.action == "brand.policy_updated")).one()
        assert entry.after == {}


class TestRegionLock:
    def test_cities_are_normalised_and_replaced(self, db: Session, owner: User) -> None:
        brand = register(db, owner)

        cities = brand_service.set_excluded_cities(
            db, brand_id=brand.id, cities=["lahore", " KARACHI ", "lahore"], actor=owner
        )
        db.commit()

        assert cities == ["Karachi", "Lahore"]

        cities = brand_service.set_excluded_cities(
            db, brand_id=brand.id, cities=["Multan"], actor=owner
        )
        db.commit()
        assert cities == ["Multan"]


class TestDashboard:
    def test_it_reports_what_the_brand_still_has_to_do(
        self, db: Session, owner: User, local_storage
    ) -> None:
        brand = register(db, owner)

        view = brand_service.dashboard(db, brand.id)
        assert view.status == VerificationStatus.PENDING
        assert view.documents_missing == list(brand_service.REQUIRED_DOCUMENTS)
        assert view.can_request_verification is False
        assert view.live_lots == 0

        supply_required_documents(db, brand, owner)
        view = brand_service.dashboard(db, brand.id)
        assert view.documents_missing == []
        assert view.can_request_verification is True

    def test_a_missing_brand_is_a_clear_error(self, db: Session) -> None:
        with pytest.raises(NotFound):
            brand_service.dashboard(db, "no-such-brand")


class TestAuditService:
    def test_credentials_never_reach_the_log(self) -> None:
        """The table is append only, so a leaked secret cannot be deleted."""
        redacted = audit_service.redact(
            {"name": "Brand", "password_hash": "abc", "api_key": "sk-123"}
        )
        assert redacted["name"] == "Brand"
        assert redacted["password_hash"] == audit_service.REDACTED
        assert redacted["api_key"] == audit_service.REDACTED

    def test_a_diff_shows_only_what_moved(self) -> None:
        changed = audit_service.diff({"a": 1, "b": 2, "c": 3}, {"a": 1, "b": 20, "c": 3})
        assert changed == {"b": {"from": 2, "to": 20}}

    def test_a_failed_audit_write_does_not_break_the_action(self, db: Session, monkeypatch) -> None:
        """A payout that fails because logging failed is the worse outcome."""

        def boom(*args, **kwargs):
            raise RuntimeError("database on fire")

        monkeypatch.setattr(db, "add", boom)

        assert audit_service.record(db, action="x", entity_type="y") is None
