"""Week 22: the approval gate, brand protection and who may see a listing.

This file guards the single promise that makes a surplus marketplace sellable
to a brand: nothing with your name on it reaches a buyer until you say so, and
afterwards you can prove what you agreed to.

The visibility tests are the ones to read first. They assert against
`visibility_filter`, which is the only definition of what a buyer may see, so
a second copy of those conditions written inline in a future search endpoint
would show up here as a failure rather than as a private lot in a public
result.
"""

from __future__ import annotations

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from catalog_helpers import BASE_LOT, build_submitted_lot
from khazana.core.errors import Conflict, ValidationFailed
from khazana.models import (
    Brand,
    BrandExcludedCity,
    ListingApproval,
    Lot,
    LotExcludedCity,
    ResellerProfile,
    User,
)
from khazana.models.enums import (
    ApprovalAction,
    LotStatus,
    UserRole,
    VerificationStatus,
    Visibility,
)
from khazana.services import approval_service, catalog_service


@pytest.fixture
def brand_owner(two_brands) -> tuple[Brand, User]:  # type: ignore[no-untyped-def]
    (brand, owner), _ = two_brands
    return brand, owner


@pytest.fixture
def submitted(db: Session, brand_owner, category) -> Lot:  # type: ignore[no-untyped-def]
    brand, owner = brand_owner
    return build_submitted_lot(db, brand, owner, category.id)


def make_reseller(db: Session, *, phone: str, city: str, status: VerificationStatus) -> User:
    user = User(phone=phone, full_name="Reseller", role=UserRole.RESELLER)
    db.add(user)
    db.flush()
    db.add(ResellerProfile(user_id=user.id, business_name="Shop", city=city, status=status))
    db.commit()
    return user


class TestApprovalGate:
    def test_approving_publishes_and_stamps_who_approved_it(
        self, db: Session, submitted: Lot, brand_owner
    ) -> None:
        _, owner = brand_owner
        approval_service.approve(db, lot=submitted, actor=owner)
        db.commit()

        assert submitted.status == LotStatus.LIVE
        assert submitted.approved_at is not None
        assert submitted.approved_by_user_id == owner.id
        assert submitted.is_publicly_visible

    def test_approving_without_publishing_leaves_it_approved_but_invisible(
        self, db: Session, submitted: Lot, brand_owner
    ) -> None:
        """Approving and publishing are different decisions.

        A brand may approve now and release when the season turns.
        """
        _, owner = brand_owner
        approval_service.approve(db, lot=submitted, actor=owner, publish=False)
        db.commit()

        assert submitted.status == LotStatus.APPROVED
        assert submitted.approved_at is not None
        assert not submitted.is_publicly_visible

    def test_only_a_submitted_lot_can_be_approved(self, db: Session, brand_owner, category) -> None:
        """A draft cannot be approved into existence.

        Without this, the readiness checks could be skipped entirely by
        calling approve on a half built lot.
        """
        brand, owner = brand_owner
        draft = catalog_service.create_lot(
            db,
            brand_id=brand.id,
            actor=owner,
            data={**BASE_LOT, "category_id": category.id},
        )
        db.commit()

        with pytest.raises(Conflict, match="awaiting approval"):
            approval_service.approve(db, lot=draft, actor=owner)

    def test_an_unverified_brand_cannot_put_stock_live(
        self, db: Session, submitted: Lot, brand_owner
    ) -> None:
        """Checked at the gate, not only at registration.

        A brand suspended after submitting must not have a queued lot slip
        out while nobody is looking.
        """
        brand, owner = brand_owner
        brand.status = VerificationStatus.SUSPENDED
        db.commit()

        with pytest.raises(Conflict, match="suspended"):
            approval_service.approve(db, lot=submitted, actor=owner)
        assert submitted.status == LotStatus.PENDING_APPROVAL

    def test_readiness_is_rechecked_at_the_gate(
        self, db: Session, submitted: Lot, brand_owner
    ) -> None:
        """A photograph removed after submission has to block approval.

        The brand is about to put its name on whatever is in the listing now,
        not on what it contained when it was submitted.
        """
        _, owner = brand_owner
        # Removing a photograph needs an editable status, so this reproduces
        # what a rejection and a re-submission would leave behind.
        submitted.status = LotStatus.DRAFT
        db.commit()
        catalog_service.remove_photo(
            db, lot=submitted, actor=owner, photo_id=submitted.photos[0].id
        )
        submitted.status = LotStatus.PENDING_APPROVAL
        db.commit()

        with pytest.raises(ValidationFailed, match="no longer ready"):
            approval_service.approve(db, lot=submitted, actor=owner)

    def test_the_approval_record_snapshots_the_listing_as_approved(
        self, db: Session, submitted: Lot, brand_owner
    ) -> None:
        """The evidence the brand is promised.

        A later edit cannot change what the snapshot says, which is the whole
        point of recording it rather than reading the lot back.
        """
        _, owner = brand_owner
        approval_service.approve(db, lot=submitted, actor=owner, note="Cleared for sale")
        db.commit()

        entry = db.scalars(
            select(ListingApproval).where(
                ListingApproval.lot_id == submitted.id,
                ListingApproval.action == ApprovalAction.APPROVED,
            )
        ).one()

        assert entry.snapshot is not None
        assert entry.snapshot["lot_price_pkr"] == 30_000
        assert entry.snapshot["total_pieces"] == 100
        assert entry.snapshot["manifest_pieces"] == 100
        assert len(entry.snapshot["photo_keys"]) == 3  # type: ignore[arg-type]
        assert entry.note == "Cleared for sale"
        assert entry.actor_user_id == owner.id

    def test_the_snapshot_survives_a_later_price_change(
        self, db: Session, submitted: Lot, brand_owner
    ) -> None:
        """What was approved stays recorded even after the lot moves on."""
        _, owner = brand_owner
        approval_service.approve(db, lot=submitted, actor=owner, publish=False)
        db.commit()

        catalog_service.update_lot(
            db, lot=submitted, actor=owner, changes={"lot_price_pkr": 45_000}
        )
        db.commit()

        entry = db.scalars(
            select(ListingApproval).where(ListingApproval.action == ApprovalAction.APPROVED)
        ).one()
        assert entry.snapshot is not None
        assert entry.snapshot["lot_price_pkr"] == 30_000
        # The material change reset the approval, which is the other half of
        # the promise.
        assert submitted.status == LotStatus.DRAFT


class TestRejection:
    def test_a_rejection_needs_a_usable_reason(
        self, db: Session, submitted: Lot, brand_owner
    ) -> None:
        """ "No" with no reason generates a support ticket, not a fix."""
        _, owner = brand_owner
        with pytest.raises(ValidationFailed, match="what needs fixing"):
            approval_service.reject(db, lot=submitted, actor=owner, note="bad")
        assert submitted.status == LotStatus.PENDING_APPROVAL

    def test_a_rejected_lot_returns_to_draft_so_it_can_be_fixed(
        self, db: Session, submitted: Lot, brand_owner
    ) -> None:
        _, owner = brand_owner
        approval_service.reject(
            db,
            lot=submitted,
            actor=owner,
            note="The label photograph is out of focus, please retake it.",
        )
        db.commit()

        assert submitted.status == LotStatus.DRAFT
        trail = approval_service.approval_trail(db, lot_id=submitted.id)
        assert [entry.action for entry in trail] == [
            ApprovalAction.SUBMITTED,
            ApprovalAction.REJECTED,
        ]


class TestWithdrawPauseResume:
    def test_pausing_keeps_the_approval_so_resuming_needs_no_second_review(
        self, db: Session, submitted: Lot, brand_owner
    ) -> None:
        _, owner = brand_owner
        approval_service.approve(db, lot=submitted, actor=owner)
        db.commit()

        approval_service.pause(db, lot=submitted, actor=owner, note="Stock counting")
        db.commit()
        assert submitted.status == LotStatus.PAUSED
        assert submitted.approved_at is not None

        approval_service.resume(db, lot=submitted, actor=owner)
        db.commit()
        assert submitted.status == LotStatus.LIVE

    def test_withdrawing_clears_the_approval(
        self, db: Session, submitted: Lot, brand_owner
    ) -> None:
        """Otherwise a withdrawn lot could be relisted on an old approval.

        The approval was given for a price and a piece count. Reviving the lot
        a season later without a fresh decision would put the brand's name on
        terms it never agreed to.
        """
        _, owner = brand_owner
        approval_service.approve(db, lot=submitted, actor=owner)
        db.commit()

        approval_service.withdraw(db, lot=submitted, actor=owner, note="Sold elsewhere")
        db.commit()

        assert submitted.status == LotStatus.WITHDRAWN
        assert submitted.approved_at is None
        assert submitted.approved_by_user_id is None

    def test_a_paused_lot_that_lost_its_approval_cannot_simply_resume(
        self, db: Session, submitted: Lot, brand_owner
    ) -> None:
        _, owner = brand_owner
        approval_service.approve(db, lot=submitted, actor=owner)
        approval_service.pause(db, lot=submitted, actor=owner)
        db.commit()

        submitted.approved_at = None
        db.commit()

        with pytest.raises(Conflict, match="approved again"):
            approval_service.resume(db, lot=submitted, actor=owner)

    def test_withdrawing_keeps_the_lot_and_its_history(
        self, db: Session, submitted: Lot, brand_owner
    ) -> None:
        """Withdraw is not a delete.

        The manifest and the approval trail survive, because the brand may
        relist next season and any order already placed has to resolve.
        """
        _, owner = brand_owner
        approval_service.withdraw(db, lot=submitted, actor=owner)
        db.commit()

        assert db.get(Lot, submitted.id) is not None
        assert len(submitted.manifest_lines) == 4
        assert len(approval_service.approval_trail(db, lot_id=submitted.id)) == 2


class TestBrandProtection:
    def test_unbranded_needs_a_label_first(self, db: Session, submitted: Lot, brand_owner) -> None:
        """An unlabelled listing reads as a scam.

        Showing "Unknown" where a brand name belongs loses the buyer, so the
        label is required before the protection level can be used.
        """
        brand, owner = brand_owner
        with pytest.raises(ValidationFailed, match="unbranded label"):
            approval_service.set_visibility(
                db, lot=submitted, actor=owner, visibility=Visibility.UNBRANDED
            )

        brand.unbranded_label = "Premium Pakistani lawn surplus"
        db.commit()

        approval_service.set_visibility(
            db, lot=submitted, actor=owner, visibility=Visibility.UNBRANDED
        )
        db.commit()
        assert submitted.visibility == Visibility.UNBRANDED

    def test_protection_can_be_tightened_while_the_lot_is_live(
        self, db: Session, submitted: Lot, brand_owner
    ) -> None:
        """The action a brand takes in a hurry, usually after a complaint.

        Making them pause first would leave the listing public while they work
        out how.
        """
        _, owner = brand_owner
        approval_service.approve(db, lot=submitted, actor=owner, visibility=Visibility.PUBLIC)
        db.commit()
        assert submitted.status == LotStatus.LIVE

        approval_service.set_visibility(
            db, lot=submitted, actor=owner, visibility=Visibility.PRIVATE
        )
        db.commit()
        assert submitted.visibility == Visibility.PRIVATE
        assert submitted.status == LotStatus.LIVE

    def test_the_city_holding_the_stock_cannot_be_excluded(
        self, db: Session, submitted: Lot, brand_owner
    ) -> None:
        _, owner = brand_owner
        with pytest.raises(ValidationFailed, match="held in Lahore"):
            approval_service.set_region_lock(
                db, lot=submitted, actor=owner, cities=["Karachi", "Lahore"]
            )

    def test_a_per_lot_region_lock_replaces_the_brand_default(
        self, db: Session, submitted: Lot, brand_owner
    ) -> None:
        """Override, not union.

        A brand that excludes Lahore by default but runs a clearance lot
        specifically for Lahore needs the override to win, and a union would
        make that impossible to express.
        """
        brand, owner = brand_owner
        db.add(BrandExcludedCity(brand_id=brand.id, city="Karachi"))
        db.commit()

        assert approval_service.excluded_cities_for(db, submitted) == ["Karachi"]

        approval_service.set_region_lock(db, lot=submitted, actor=owner, cities=["Multan"])
        db.commit()

        assert approval_service.excluded_cities_for(db, submitted) == ["Multan"]

    def test_duplicate_cities_are_collapsed(self, db: Session, submitted: Lot, brand_owner) -> None:
        _, owner = brand_owner
        cities = approval_service.set_region_lock(
            db, lot=submitted, actor=owner, cities=["Multan", "multan", " Multan ", ""]
        )
        db.commit()
        assert cities == ["Multan"]


class TestVisibilityRules:
    """What a buyer may see. One definition, exercised from every angle."""

    def _visible(
        self,
        db: Session,
        *,
        role: UserRole | None = UserRole.RESELLER,
        verified: bool = False,
        city: str | None = None,
    ) -> list[str]:
        rows = db.scalars(
            select(Lot).where(
                approval_service.visibility_filter(
                    role=role, reseller_is_verified=verified, city=city
                )
            )
        ).all()
        return [lot.id for lot in rows]

    def test_a_draft_is_never_visible_to_a_buyer(self, db: Session, submitted: Lot) -> None:
        assert submitted.id not in self._visible(db)

    def test_a_pending_lot_is_never_visible_to_a_buyer(self, db: Session, submitted: Lot) -> None:
        assert submitted.status == LotStatus.PENDING_APPROVAL
        assert submitted.id not in self._visible(db)

    def test_a_public_live_lot_is_visible(self, db: Session, submitted: Lot, brand_owner) -> None:
        _, owner = brand_owner
        approval_service.approve(db, lot=submitted, actor=owner, visibility=Visibility.PUBLIC)
        db.commit()
        assert submitted.id in self._visible(db)

    def test_a_private_lot_is_hidden_from_an_unverified_reseller(
        self, db: Session, submitted: Lot, brand_owner
    ) -> None:
        """Private means verified resellers only.

        The fixture brand's default protection level is private, so this is
        the path most lots take.
        """
        _, owner = brand_owner
        approval_service.approve(db, lot=submitted, actor=owner, visibility=Visibility.PRIVATE)
        db.commit()

        assert submitted.id not in self._visible(db, verified=False)
        assert submitted.id in self._visible(db, verified=True)

    def test_an_unbranded_lot_is_visible_to_everyone(
        self, db: Session, submitted: Lot, brand_owner
    ) -> None:
        brand, owner = brand_owner
        brand.unbranded_label = "Surplus lawn"
        db.commit()
        approval_service.approve(db, lot=submitted, actor=owner, visibility=Visibility.UNBRANDED)
        db.commit()
        assert submitted.id in self._visible(db, verified=False)

    def test_the_database_refuses_a_live_lot_with_no_approval(
        self, db: Session, submitted: Lot, brand_owner
    ) -> None:
        """The state the visibility filter guards against cannot be created.

        `visibility_filter` requires `approved_at` as well as a live status.
        That condition is defence in depth, and this test proves it is the
        second line rather than the only one: stripping the approval off a
        live lot is refused outright by the CHECK constraint.
        """
        _, owner = brand_owner
        approval_service.approve(db, lot=submitted, actor=owner, visibility=Visibility.PUBLIC)
        db.commit()
        assert submitted.id in self._visible(db)

        with pytest.raises(IntegrityError, match="live_requires_approval"):
            db.query(Lot).filter(Lot.id == submitted.id).update(
                {"approved_at": None}, synchronize_session=False
            )
        db.rollback()

    def test_the_region_lock_hides_a_lot_from_an_excluded_city(
        self, db: Session, submitted: Lot, brand_owner
    ) -> None:
        """The first objection a brand raises.

        Discounted stock turning up next to its own shop is the thing that
        stops a brand signing at all.
        """
        _, owner = brand_owner
        approval_service.approve(db, lot=submitted, actor=owner, visibility=Visibility.PUBLIC)
        approval_service.set_region_lock(db, lot=submitted, actor=owner, cities=["Karachi"])
        db.commit()

        assert submitted.id not in self._visible(db, city="Karachi")
        assert submitted.id not in self._visible(db, city="karachi")
        assert submitted.id in self._visible(db, city="Multan")
        assert submitted.id in self._visible(db, city=None)

    def test_the_brand_default_lock_applies_when_the_lot_has_no_list(
        self, db: Session, submitted: Lot, brand_owner
    ) -> None:
        brand, owner = brand_owner
        db.add(BrandExcludedCity(brand_id=brand.id, city="Karachi"))
        approval_service.approve(db, lot=submitted, actor=owner, visibility=Visibility.PUBLIC)
        db.commit()

        assert submitted.id not in self._visible(db, city="Karachi")

    def test_an_empty_per_lot_list_overrides_the_brand_default(
        self, db: Session, submitted: Lot, brand_owner
    ) -> None:
        """A lot sold everywhere, under a brand that excludes a city.

        The per lot list wins when it exists. An empty one does not exist as
        far as the override is concerned, so the brand default applies again,
        and that is why `set_region_lock` with an empty list is documented as
        matching the default rather than clearing it.
        """
        brand, owner = brand_owner
        db.add(BrandExcludedCity(brand_id=brand.id, city="Karachi"))
        approval_service.approve(db, lot=submitted, actor=owner, visibility=Visibility.PUBLIC)
        db.commit()

        db.add(LotExcludedCity(lot_id=submitted.id, brand_id=brand.id, city="Multan"))
        db.commit()

        # Karachi is on the brand list but not on the lot's own list, and the
        # lot's own list is what counts now.
        assert submitted.id in self._visible(db, city="Karachi")
        assert submitted.id not in self._visible(db, city="Multan")

    def test_an_admin_sees_everything_including_drafts(self, db: Session, submitted: Lot) -> None:
        assert submitted.id in self._visible(db, role=UserRole.ADMIN)


class TestPresentation:
    def test_an_unbranded_lot_hides_the_brand_name_from_a_buyer(
        self, db: Session, submitted: Lot, brand_owner
    ) -> None:
        brand, owner = brand_owner
        brand.unbranded_label = "Premium lawn surplus"
        db.commit()
        approval_service.set_visibility(
            db, lot=submitted, actor=owner, visibility=Visibility.UNBRANDED
        )
        db.commit()

        shown = approval_service.present(db, submitted, viewer_role=UserRole.RESELLER)
        assert shown.brand_name == "Premium lawn surplus"
        assert shown.brand_is_hidden
        assert brand.name not in shown.brand_name

    def test_the_owning_brand_and_an_admin_still_see_the_real_name(
        self, db: Session, submitted: Lot, brand_owner
    ) -> None:
        """Hiding the name from its owner would be a bug dressed as a feature."""
        brand, owner = brand_owner
        brand.unbranded_label = "Premium lawn surplus"
        db.commit()
        approval_service.set_visibility(
            db, lot=submitted, actor=owner, visibility=Visibility.UNBRANDED
        )
        db.commit()

        for role in (UserRole.BRAND, UserRole.ADMIN):
            shown = approval_service.present(db, submitted, viewer_role=role)
            assert shown.brand_name == brand.name
            assert not shown.brand_is_hidden


class TestQueue:
    def test_the_queue_puts_the_riskiest_lot_first(
        self, db: Session, brand_owner, category
    ) -> None:
        """The risk score orders the queue and decides nothing.

        A grade C lot with no description scores worse than a clean grade A
        one, so the person reviewing sees it sooner. See
        `docs/ai-architecture.md` section 2.
        """
        brand, owner = brand_owner
        clean = build_submitted_lot(
            db, brand, owner, category.id, description="Full season detail, 100 pieces."
        )
        risky = build_submitted_lot(db, brand, owner, category.id)

        queue = approval_service.pending_queue(db, brand_ids=[brand.id])
        assert len(queue) == 2
        assert queue[0].risk_score >= queue[1].risk_score
        assert {item.lot.id for item in queue} == {clean.id, risky.id}
        assert all(item.risk_band in {"low", "medium", "high"} for item in queue)

    def test_the_queue_is_scoped_to_the_callers_brands(
        self, db: Session, two_brands, category
    ) -> None:
        (first, first_owner), (second, _) = two_brands
        build_submitted_lot(db, first, first_owner, category.id)

        assert len(approval_service.pending_queue(db, brand_ids=[first.id])) == 1
        assert approval_service.pending_queue(db, brand_ids=[second.id]) == []
        # None means every brand, which the router only passes for an admin.
        assert len(approval_service.pending_queue(db, brand_ids=None)) == 1
