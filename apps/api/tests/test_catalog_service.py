"""M3: lot creation, the manifest rule, the photo pipeline and the state machine.

The tests that matter most here are the ones guarding a promise to a buyer or
to a brand, rather than the ones proving a field round trips:

- The manifest sum rule, which is what a buyer trusts or rejects a lot on.
- The discount band, which stops a pricing mistake undercutting a brand's own
  retail channel.
- The state machine, which is the only reason an unapproved lot cannot reach a
  buyer.
- Material edits after approval, which is the difference between an approval
  record that means something and one that does not.
"""

from __future__ import annotations

from datetime import UTC, date, datetime

import pytest
from sqlalchemy.orm import Session

from catalog_helpers import (
    BASE_LOT,
    balanced_manifest,
    jpeg_bytes,
    make_live,
    ready_lot,
)
from khazana.core.errors import Conflict, ValidationFailed
from khazana.models import Brand, BrandPolicy, Category, Lot, User
from khazana.models.enums import ConditionGrade, LotStatus, PhotoKind, Visibility
from khazana.services import catalog_service


@pytest.fixture
def brand_owner(two_brands) -> tuple[Brand, User]:  # type: ignore[no-untyped-def]
    (brand, owner), _ = two_brands
    return brand, owner


@pytest.fixture
def lot(db: Session, brand_owner, category: Category) -> Lot:  # type: ignore[no-untyped-def]
    brand, owner = brand_owner
    created = catalog_service.create_lot(
        db,
        brand_id=brand.id,
        actor=owner,
        data={**BASE_LOT, "category_id": category.id},
    )
    db.commit()
    return created


class TestCreateLot:
    def test_starts_as_a_draft_at_the_brand_default_visibility(
        self, db: Session, brand_owner, category: Category
    ) -> None:
        brand, owner = brand_owner
        created = catalog_service.create_lot(
            db, brand_id=brand.id, actor=owner, data={**BASE_LOT, "category_id": category.id}
        )
        assert created.status == LotStatus.DRAFT
        # The fixture brand's policy sets private as the default.
        assert created.visibility == Visibility.PRIVATE
        assert created.approved_at is None

    def test_lot_code_is_unique_and_leaks_no_sequence(
        self, db: Session, brand_owner, category: Category
    ) -> None:
        """Codes are random, not sequential.

        A sequential code publishes how many lots the platform has listed,
        which on a marketplace this size is not information worth giving away.
        """
        brand, owner = brand_owner
        codes = {
            catalog_service.create_lot(
                db,
                brand_id=brand.id,
                actor=owner,
                data={**BASE_LOT, "category_id": category.id},
            ).lot_code
            for _ in range(10)
        }
        assert len(codes) == 10
        for code in codes:
            assert code.startswith("LOT-")
            # No character that is confusable when read aloud on a phone call.
            assert not set(code[4:]) & set("O0IL1S5")

    def test_rejects_a_field_it_does_not_own(
        self, db: Session, brand_owner, category: Category
    ) -> None:
        """Status cannot be set at creation.

        Every status change goes through the state machine. Accepting one here
        would be a way around it.
        """
        brand, owner = brand_owner
        with pytest.raises(ValidationFailed, match="cannot be set here"):
            catalog_service.create_lot(
                db,
                brand_id=brand.id,
                actor=owner,
                data={**BASE_LOT, "category_id": category.id, "status": LotStatus.LIVE},
            )

    def test_a_parent_category_is_refused(
        self, db: Session, brand_owner, category: Category
    ) -> None:
        brand, owner = brand_owner
        child = Category(name="Lawn", slug="lawn", parent_id=category.id)
        db.add(child)
        db.commit()
        db.refresh(category)

        with pytest.raises(ValidationFailed, match="subcategor"):
            catalog_service.create_lot(
                db,
                brand_id=brand.id,
                actor=owner,
                data={**BASE_LOT, "category_id": category.id},
            )

    def test_a_category_with_a_shelf_life_needs_an_expiry_date(
        self, db: Session, brand_owner
    ) -> None:
        cosmetics = Category(name="Cosmetics", slug="cosmetics", requires_expiry=True)
        db.add(cosmetics)
        db.commit()
        brand, owner = brand_owner

        with pytest.raises(ValidationFailed, match="expiry date"):
            catalog_service.create_lot(
                db,
                brand_id=brand.id,
                actor=owner,
                data={**BASE_LOT, "category_id": cosmetics.id},
            )

        created = catalog_service.create_lot(
            db,
            brand_id=brand.id,
            actor=owner,
            data={
                **BASE_LOT,
                "category_id": cosmetics.id,
                "expiry_date": date(2027, 6, 30),
            },
        )
        assert created.expiry_date == date(2027, 6, 30)


class TestCommercialGuards:
    """The money checks, which exist for the error message.

    The database has CHECK constraints for all of this. The point of checking
    again here is that a brand which priced a lot wrong gets told which number
    to change, rather than a constraint violation.
    """

    def test_a_price_above_retail_is_refused(
        self, db: Session, brand_owner, category: Category
    ) -> None:
        brand, owner = brand_owner
        with pytest.raises(ValidationFailed, match="above the retail value"):
            catalog_service.create_lot(
                db,
                brand_id=brand.id,
                actor=owner,
                data={**BASE_LOT, "category_id": category.id, "lot_price_pkr": 200_000},
            )

    def test_a_discount_below_the_brand_floor_is_refused_with_the_right_number(
        self, db: Session, brand_owner, category: Category
    ) -> None:
        """A 20 percent discount against a 50 percent floor.

        The message has to name the price that would work, because "invalid
        discount" leaves the brand to do the arithmetic.
        """
        brand, owner = brand_owner
        with pytest.raises(ValidationFailed) as caught:
            catalog_service.create_lot(
                db,
                brand_id=brand.id,
                actor=owner,
                data={**BASE_LOT, "category_id": category.id, "lot_price_pkr": 80_000},
            )
        message = str(caught.value)
        assert "20 percent" in message
        assert "50 percent" in message
        # retail total 100,000 at a 50 percent floor means 50,000.
        assert "50,000" in message

    def test_a_discount_above_the_brand_ceiling_is_refused(
        self, db: Session, brand_owner, category: Category
    ) -> None:
        """The guard that protects the brand from its own typo.

        A 95 percent discount is almost always a missing digit, and it
        undercuts the brand's own retail channel.
        """
        brand, owner = brand_owner
        # Retail is raised for this case so that a 95 percent discount still
        # clears the 25,000 minimum lot value. Otherwise the minimum fires
        # first and this test proves the wrong guard.
        with pytest.raises(ValidationFailed, match="ceiling"):
            catalog_service.create_lot(
                db,
                brand_id=brand.id,
                actor=owner,
                data={
                    **BASE_LOT,
                    "category_id": category.id,
                    "retail_price_per_piece_pkr": 10_000,
                    "lot_price_pkr": 50_000,
                },
            )

    def test_a_lot_below_the_brand_minimum_value_is_refused(
        self, db: Session, brand_owner, category: Category
    ) -> None:
        brand, owner = brand_owner
        policy = db.query(BrandPolicy).filter_by(brand_id=brand.id).one()
        policy.min_lot_value_pkr = 50_000
        db.commit()

        with pytest.raises(ValidationFailed, match="minimum lot value"):
            catalog_service.create_lot(
                db,
                brand_id=brand.id,
                actor=owner,
                data={**BASE_LOT, "category_id": category.id},
            )

    def test_a_minimum_order_above_the_lot_size_is_refused(
        self, db: Session, brand_owner, category: Category
    ) -> None:
        brand, owner = brand_owner
        with pytest.raises(ValidationFailed, match="minimum order"):
            catalog_service.create_lot(
                db,
                brand_id=brand.id,
                actor=owner,
                data={**BASE_LOT, "category_id": category.id, "min_order_pieces": 500},
            )


class TestManifest:
    """The rule a buyer judges a lot on."""

    def test_a_balanced_manifest_is_accepted(self, db: Session, lot: Lot, brand_owner) -> None:
        _, owner = brand_owner
        lines = catalog_service.set_manifest(db, lot=lot, actor=owner, lines=balanced_manifest())
        db.commit()
        assert len(lines) == 4
        assert lot.manifest_total == 100
        assert lot.is_manifest_balanced

    def test_a_short_manifest_is_refused_and_says_by_how_much(
        self, db: Session, lot: Lot, brand_owner
    ) -> None:
        _, owner = brand_owner
        with pytest.raises(ValidationFailed) as caught:
            catalog_service.set_manifest(
                db,
                lot=lot,
                actor=owner,
                lines=[{"size": "S", "color": "blue", "pieces": 90}],
            )
        message = str(caught.value)
        assert "90" in message
        assert "100" in message
        assert "10 less than" in message

    def test_an_over_long_manifest_is_refused(self, db: Session, lot: Lot, brand_owner) -> None:
        _, owner = brand_owner
        with pytest.raises(ValidationFailed) as caught:
            catalog_service.set_manifest(
                db,
                lot=lot,
                actor=owner,
                lines=[{"size": "S", "color": "blue", "pieces": 110}],
            )
        assert "10 more than" in str(caught.value)

    def test_a_duplicate_size_and_colour_is_refused(
        self, db: Session, lot: Lot, brand_owner
    ) -> None:
        """Caught before the database, which has a unique constraint.

        The constraint's own message names an index, which tells a brand
        nothing about which two rows to combine.
        """
        _, owner = brand_owner
        with pytest.raises(ValidationFailed, match="appears twice"):
            catalog_service.set_manifest(
                db,
                lot=lot,
                actor=owner,
                lines=[
                    {"size": "S", "color": "Blue", "pieces": 50},
                    {"size": "s", "color": "blue", "pieces": 50},
                ],
            )

    def test_a_non_numeric_piece_count_is_refused_by_line_number(
        self, db: Session, lot: Lot, brand_owner
    ) -> None:
        _, owner = brand_owner
        with pytest.raises(ValidationFailed, match="Line 2"):
            catalog_service.set_manifest(
                db,
                lot=lot,
                actor=owner,
                lines=[
                    {"size": "S", "color": "blue", "pieces": 50},
                    {"size": "M", "color": "blue", "pieces": "fifty"},
                ],
            )

    def test_setting_the_manifest_replaces_rather_than_appends(
        self, db: Session, lot: Lot, brand_owner
    ) -> None:
        """Replace semantics, so a half applied edit cannot leave the sum wrong."""
        _, owner = brand_owner
        catalog_service.set_manifest(db, lot=lot, actor=owner, lines=balanced_manifest())
        db.commit()

        catalog_service.set_manifest(
            db,
            lot=lot,
            actor=owner,
            lines=[{"size": "Free", "color": "mixed", "pieces": 100}],
        )
        db.commit()

        assert len(lot.manifest_lines) == 1
        assert lot.manifest_total == 100

    def test_an_empty_manifest_is_refused(self, db: Session, lot: Lot, brand_owner) -> None:
        _, owner = brand_owner
        with pytest.raises(ValidationFailed, match="at least one line"):
            catalog_service.set_manifest(db, lot=lot, actor=owner, lines=[])

    def test_lowering_the_total_below_the_manifest_is_refused(
        self, db: Session, lot: Lot, brand_owner
    ) -> None:
        """The inconsistency the database trigger would otherwise catch."""
        _, owner = brand_owner
        catalog_service.set_manifest(db, lot=lot, actor=owner, lines=balanced_manifest())
        db.commit()

        # The price moves with the total because halving the lot alone would
        # put the discount under the brand floor, and that guard runs first.
        # 25,000 against a retail total of 50,000 is exactly the 50 percent
        # floor and clears the 25,000 minimum.
        with pytest.raises(ValidationFailed, match="Change the manifest first"):
            catalog_service.update_lot(
                db,
                lot=lot,
                actor=owner,
                changes={"total_pieces": 50, "lot_price_pkr": 25_000},
            )


class TestPhotoPipeline:
    def test_an_upload_is_shrunk_and_the_saving_is_recorded(
        self, db: Session, lot: Lot, brand_owner
    ) -> None:
        """Nothing is stored as uploaded.

        A 1600 pixel photograph comes back at the 1024 pixel cap, and the
        stored size is recorded so the compression can be measured rather than
        assumed.
        """
        _, owner = brand_owner
        raw = jpeg_bytes(width=1600, height=1200)
        photo = catalog_service.add_photo(
            db, lot=lot, actor=owner, data=raw, content_type="image/jpeg", kind=PhotoKind.FRONT
        )
        db.commit()

        assert photo.is_optimised
        assert photo.width == 1024
        assert photo.height == 768
        assert photo.bytes_stored is not None
        assert photo.bytes_stored < len(raw)
        assert photo.sort_order == 1

    def test_a_file_that_is_not_an_image_is_refused(
        self, db: Session, lot: Lot, brand_owner
    ) -> None:
        """The declared type is not trusted.

        An HTML file uploaded as image/png and served back later is a stored
        cross site scripting bug, so the magic bytes decide.
        """
        _, owner = brand_owner
        with pytest.raises(ValidationFailed):
            catalog_service.add_photo(
                db,
                lot=lot,
                actor=owner,
                data=b"<html><script>alert(1)</script></html>",
                content_type="image/png",
                kind=PhotoKind.FRONT,
            )

    def test_the_same_photograph_twice_is_refused(self, db: Session, lot: Lot, brand_owner) -> None:
        """Brands re-upload when a phone upload looks like it stalled.

        Without this each duplicate is paid for twice: once in storage and
        again in vision tokens on the next draft.
        """
        _, owner = brand_owner
        raw = jpeg_bytes()
        catalog_service.add_photo(
            db, lot=lot, actor=owner, data=raw, content_type="image/jpeg", kind=PhotoKind.FRONT
        )
        db.commit()

        with pytest.raises(ValidationFailed, match="same image"):
            catalog_service.add_photo(
                db, lot=lot, actor=owner, data=raw, content_type="image/jpeg", kind=PhotoKind.BACK
            )

    def test_the_photo_limit_is_enforced(self, db: Session, lot: Lot, brand_owner) -> None:
        _, owner = brand_owner
        for index in range(catalog_service.MAX_PHOTOS_PER_LOT):
            catalog_service.add_photo(
                db,
                lot=lot,
                actor=owner,
                data=jpeg_bytes(width=200 + index, height=200, seed=index),
                content_type="image/jpeg",
                kind=PhotoKind.FRONT,
            )
        db.commit()

        with pytest.raises(ValidationFailed, match="which is the limit"):
            catalog_service.add_photo(
                db,
                lot=lot,
                actor=owner,
                data=jpeg_bytes(width=999, height=200, seed=500),
                content_type="image/jpeg",
                kind=PhotoKind.FRONT,
            )

    def test_reordering_requires_the_whole_set(self, db: Session, lot: Lot, brand_owner) -> None:
        """A partial reorder leaves duplicate positions.

        The gallery order would then depend on how the database felt about the
        query, which is not an order at all.
        """
        _, owner = brand_owner
        ready_lot(db, lot, owner)
        ids = [photo.id for photo in lot.photos]

        with pytest.raises(ValidationFailed, match="exactly once"):
            catalog_service.reorder_photos(db, lot=lot, actor=owner, photo_ids=ids[:2])

        reordered = catalog_service.reorder_photos(
            db, lot=lot, actor=owner, photo_ids=list(reversed(ids))
        )
        db.commit()
        assert [photo.id for photo in reordered] == list(reversed(ids))
        assert [photo.sort_order for photo in reordered] == [1, 2, 3]

    def test_removing_a_photograph_closes_the_gap_in_the_order(
        self, db: Session, lot: Lot, brand_owner
    ) -> None:
        _, owner = brand_owner
        ready_lot(db, lot, owner)
        middle = sorted(lot.photos, key=lambda p: p.sort_order)[1]

        catalog_service.remove_photo(db, lot=lot, actor=owner, photo_id=middle.id)
        db.commit()

        orders = sorted(photo.sort_order for photo in lot.photos)
        assert orders == [1, 2]

    def test_a_photograph_backing_a_defect_cannot_be_removed(
        self, db: Session, lot: Lot, brand_owner
    ) -> None:
        """Otherwise the listing claims a defect the buyer cannot see."""
        _, owner = brand_owner
        ready_lot(db, lot, owner)
        photo = lot.photos[0]
        catalog_service.set_defects(
            db,
            lot=lot,
            actor=owner,
            defects=[{"issue": "Faded dye on the hem", "pieces_affected": 4, "photo_id": photo.id}],
        )
        db.commit()

        with pytest.raises(Conflict, match="evidence for a listed defect"):
            catalog_service.remove_photo(db, lot=lot, actor=owner, photo_id=photo.id)


class TestDefects:
    def test_a_defect_affecting_more_pieces_than_the_lot_holds_is_refused(
        self, db: Session, lot: Lot, brand_owner
    ) -> None:
        _, owner = brand_owner
        with pytest.raises(ValidationFailed, match="only has 100"):
            catalog_service.set_defects(
                db,
                lot=lot,
                actor=owner,
                defects=[{"issue": "Loose stitching", "pieces_affected": 500}],
            )

    def test_a_defect_cannot_point_at_another_lots_photograph(
        self, db: Session, lot: Lot, brand_owner, category: Category
    ) -> None:
        brand, owner = brand_owner
        other = catalog_service.create_lot(
            db, brand_id=brand.id, actor=owner, data={**BASE_LOT, "category_id": category.id}
        )
        stray = catalog_service.add_photo(
            db,
            lot=other,
            actor=owner,
            data=jpeg_bytes(seed=99),
            content_type="image/jpeg",
            kind=PhotoKind.DEFECT,
        )
        db.commit()

        with pytest.raises(ValidationFailed, match="not on this lot"):
            catalog_service.set_defects(
                db,
                lot=lot,
                actor=owner,
                defects=[{"issue": "Scuff on the box", "pieces_affected": 2, "photo_id": stray.id}],
            )


class TestReadinessAndSubmission:
    def test_an_empty_lot_lists_every_blocker_at_once(self, db: Session, lot: Lot) -> None:
        """A checklist, not one error at a time.

        The brand should see everything outstanding while they work through
        it, rather than discovering the next problem after fixing each one.
        """
        state = catalog_service.readiness(db, lot)
        assert not state.ready
        assert any("manifest is empty" in blocker for blocker in state.blockers)
        assert any("photographs" in blocker for blocker in state.blockers)

    def test_grade_c_without_itemised_defects_is_blocked(
        self, db: Session, lot: Lot, brand_owner
    ) -> None:
        """Honesty is a commercial feature here, not a formality.

        An unmentioned defect found by a buyer loses that buyer permanently.
        """
        _, owner = brand_owner
        ready_lot(db, lot, owner)
        catalog_service.update_lot(
            db, lot=lot, actor=owner, changes={"condition_grade": ConditionGrade.C}
        )
        db.commit()

        state = catalog_service.readiness(db, lot)
        assert not state.ready
        assert any("Grade C" in blocker for blocker in state.blockers)

        catalog_service.set_defects(
            db,
            lot=lot,
            actor=owner,
            defects=[{"issue": "Minor weaving faults", "pieces_affected": 12}],
        )
        db.commit()
        assert catalog_service.readiness(db, lot).ready

    def test_a_missing_label_photograph_warns_without_blocking(
        self, db: Session, lot: Lot, brand_owner
    ) -> None:
        _, owner = brand_owner
        catalog_service.set_manifest(db, lot=lot, actor=owner, lines=balanced_manifest())
        for index, kind in enumerate((PhotoKind.FULL_LOT, PhotoKind.FRONT, PhotoKind.BACK), 1):
            catalog_service.add_photo(
                db,
                lot=lot,
                actor=owner,
                data=jpeg_bytes(seed=index),
                content_type="image/jpeg",
                kind=kind,
            )
        db.commit()

        state = catalog_service.readiness(db, lot)
        assert state.ready
        assert any("label" in warning for warning in state.warnings)

    def test_submitting_an_unready_lot_is_refused(self, db: Session, lot: Lot, brand_owner) -> None:
        _, owner = brand_owner
        with pytest.raises(ValidationFailed, match="not ready to submit"):
            catalog_service.submit_for_approval(db, lot=lot, actor=owner)
        assert lot.status == LotStatus.DRAFT

    def test_a_ready_lot_moves_to_pending_approval(
        self, db: Session, lot: Lot, brand_owner
    ) -> None:
        _, owner = brand_owner
        ready_lot(db, lot, owner)
        catalog_service.submit_for_approval(db, lot=lot, actor=owner)
        db.commit()
        assert lot.status == LotStatus.PENDING_APPROVAL


class TestStateMachine:
    def test_an_illegal_move_names_what_is_allowed(
        self, db: Session, lot: Lot, brand_owner
    ) -> None:
        """A draft cannot jump straight to live.

        This is the whole reason an unapproved listing cannot reach a buyer,
        and the CHECK constraint on the table says the same thing.
        """
        _, owner = brand_owner
        with pytest.raises(Conflict) as caught:
            catalog_service.transition(db, lot=lot, to=LotStatus.LIVE, actor=owner)
        message = str(caught.value)
        assert "draft" in message
        assert "pending_approval" in message

    def test_a_sold_lot_cannot_be_revived(self, db: Session, lot: Lot, brand_owner) -> None:
        """The one bug a marketplace cannot have is selling the same stock twice."""
        _, owner = brand_owner
        lot.status = LotStatus.SOLD
        db.commit()

        with pytest.raises(Conflict, match="cannot change state any further"):
            catalog_service.transition(db, lot=lot, to=LotStatus.LIVE, actor=owner)

    def test_a_withdrawn_lot_can_be_taken_back_to_draft(
        self, db: Session, lot: Lot, brand_owner
    ) -> None:
        """A brand pulling a lot for the season should be able to relist it."""
        _, owner = brand_owner
        catalog_service.transition(db, lot=lot, to=LotStatus.WITHDRAWN, actor=owner)
        catalog_service.transition(db, lot=lot, to=LotStatus.DRAFT, actor=owner)
        db.commit()
        assert lot.status == LotStatus.DRAFT

    def test_moving_to_the_same_status_is_a_no_op(self, db: Session, lot: Lot, brand_owner) -> None:
        _, owner = brand_owner
        assert (
            catalog_service.transition(db, lot=lot, to=LotStatus.DRAFT, actor=owner).status
            == LotStatus.DRAFT
        )


class TestEditsAfterApproval:
    """The difference between an approval record that means something and one
    that does not."""

    def test_a_live_lot_cannot_have_its_price_changed_underneath_a_buyer(
        self, db: Session, lot: Lot, brand_owner
    ) -> None:
        _, owner = brand_owner
        make_live(db, lot)

        with pytest.raises(Conflict, match="Pause it first"):
            catalog_service.update_lot(db, lot=lot, actor=owner, changes={"lot_price_pkr": 40_000})

    def test_a_non_material_change_is_allowed_while_live(
        self, db: Session, lot: Lot, brand_owner
    ) -> None:
        """Shortening the availability window does not change the goods."""
        _, owner = brand_owner
        make_live(db, lot)

        catalog_service.update_lot(
            db, lot=lot, actor=owner, changes={"available_until": date(2027, 1, 31)}
        )
        db.commit()
        assert lot.available_until == date(2027, 1, 31)
        assert lot.status == LotStatus.LIVE

    def test_a_material_change_to_an_approved_lot_resets_the_approval(
        self, db: Session, lot: Lot, brand_owner
    ) -> None:
        """The promise behind MATERIAL_FIELDS.

        A brand approved a price. Changing it has to cost the approval, or the
        approval record stops describing what a buyer is looking at. This was
        unreachable when the state machine had no APPROVED to DRAFT move.
        """
        _, owner = brand_owner
        ready_lot(db, lot, owner)
        lot.status = LotStatus.APPROVED
        lot.approved_at = datetime.now(UTC)
        db.commit()

        catalog_service.update_lot(db, lot=lot, actor=owner, changes={"lot_price_pkr": 40_000})
        db.commit()
        assert lot.status == LotStatus.DRAFT

    def test_a_material_change_to_a_paused_lot_resets_the_approval(
        self, db: Session, lot: Lot, brand_owner
    ) -> None:
        """Pausing is what a brand does in order to change something.

        The refusal on a live lot tells them to pause first, so pausing has to
        actually let them through.
        """
        _, owner = brand_owner
        ready_lot(db, lot, owner)
        make_live(db, lot)
        lot.status = LotStatus.PAUSED
        db.commit()

        catalog_service.update_lot(
            db, lot=lot, actor=owner, changes={"total_pieces": 100, "lot_price_pkr": 35_000}
        )
        db.commit()
        assert lot.status == LotStatus.DRAFT

    def test_the_manifest_cannot_be_edited_on_an_approved_lot(
        self, db: Session, lot: Lot, brand_owner
    ) -> None:
        _, owner = brand_owner
        ready_lot(db, lot, owner)
        lot.status = LotStatus.APPROVED
        db.commit()

        with pytest.raises(Conflict, match="approved lot"):
            catalog_service.set_manifest(db, lot=lot, actor=owner, lines=balanced_manifest())
