"""Schema rules: the manifest sum, the money arithmetic and the approval gate.

Each test here corresponds to a promise the platform makes to a brand or a
buyer, expressed as a database constraint rather than as a comment.
"""

from __future__ import annotations

from enum import StrEnum

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from khazana.models import Lot, ManifestLine, Order
from khazana.models.enums import ConditionGrade, LotStatus, OrderStatus, Visibility


def build_lot(db: Session, brand_id: str, category_id: str, **overrides: object) -> Lot:
    """Add a lot with sane defaults.

    ``min_order_pieces`` follows ``total_pieces`` unless overridden, so a test
    that only changes the piece count does not trip an unrelated constraint
    and report a confusing failure.
    """
    total = overrides.get("total_pieces", 100)
    defaults: dict[str, object] = {
        "lot_code": "LOT-TEST",
        "brand_id": brand_id,
        "category_id": category_id,
        "title": "Test lot",
        "condition_grade": ConditionGrade.A,
        "total_pieces": total,
        "retail_price_per_piece_pkr": 1000,
        "lot_price_pkr": 25_000,
        "min_order_pieces": total,
        "stock_city": "Lahore",
        "status": LotStatus.DRAFT,
        "visibility": Visibility.PRIVATE,
    }
    defaults.update(overrides)
    lot = Lot(**defaults)  # type: ignore[arg-type]
    db.add(lot)
    db.flush()
    return lot


class TestManifestRule:
    def test_a_balanced_manifest_is_reported_balanced(
        self, db: Session, two_brands, category
    ) -> None:  # type: ignore[no-untyped-def]
        (brand, _), _ = two_brands
        lot = build_lot(db, brand.id, category.id, total_pieces=60)
        for size, pieces in [("S", 20), ("M", 25), ("L", 15)]:
            db.add(
                ManifestLine(
                    lot_id=lot.id, brand_id=brand.id, size=size, color="black", pieces=pieces
                )
            )
        db.commit()
        db.refresh(lot)

        assert lot.manifest_total == 60
        assert lot.is_manifest_balanced

    def test_an_unbalanced_manifest_is_detected(self, db: Session, two_brands, category) -> None:  # type: ignore[no-untyped-def]
        """The rule buyers care about most.

        On PostgreSQL a deferred trigger refuses the commit. On SQLite, which
        has no such trigger, the property is still false, and the service
        layer is what refuses. Both engines agree on the answer, which is what
        this asserts.
        """
        (brand, _), _ = two_brands
        lot = build_lot(db, brand.id, category.id, total_pieces=100)
        db.add(ManifestLine(lot_id=lot.id, brand_id=brand.id, size="M", color="black", pieces=40))
        db.commit()
        db.refresh(lot)

        assert lot.manifest_total == 40
        assert not lot.is_manifest_balanced

    def test_duplicate_size_and_colour_is_rejected(self, db: Session, two_brands, category) -> None:  # type: ignore[no-untyped-def]
        """Two rows for medium black would make the manifest ambiguous."""
        (brand, _), _ = two_brands
        lot = build_lot(db, brand.id, category.id)
        db.add(ManifestLine(lot_id=lot.id, brand_id=brand.id, size="M", color="black", pieces=50))
        db.commit()

        db.add(ManifestLine(lot_id=lot.id, brand_id=brand.id, size="M", color="black", pieces=50))
        with pytest.raises(IntegrityError):
            db.commit()
        db.rollback()

    def test_zero_pieces_is_rejected(self, db: Session, two_brands, category) -> None:  # type: ignore[no-untyped-def]
        (brand, _), _ = two_brands
        lot = build_lot(db, brand.id, category.id)
        db.add(ManifestLine(lot_id=lot.id, brand_id=brand.id, size="M", color="black", pieces=0))
        with pytest.raises(IntegrityError):
            db.commit()
        db.rollback()


class TestLotConstraints:
    def test_a_lot_cannot_be_live_without_approval(self, db: Session, two_brands, category) -> None:  # type: ignore[no-untyped-def]
        """The brand protection promise, enforced by the database.

        No code path, no admin mistake and no background job can publish a lot
        the brand never approved.
        """
        (brand, _), _ = two_brands
        with pytest.raises(IntegrityError):
            build_lot(db, brand.id, category.id, status=LotStatus.LIVE, approved_at=None)
        db.rollback()

    def test_lot_price_cannot_exceed_retail(self, db: Session, two_brands, category) -> None:  # type: ignore[no-untyped-def]
        (brand, _), _ = two_brands
        with pytest.raises(IntegrityError):
            build_lot(
                db,
                brand.id,
                category.id,
                total_pieces=10,
                retail_price_per_piece_pkr=100,
                lot_price_pkr=2_000,
            )
        db.rollback()

    def test_minimum_order_cannot_exceed_the_lot(self, db: Session, two_brands, category) -> None:  # type: ignore[no-untyped-def]
        (brand, _), _ = two_brands
        with pytest.raises(IntegrityError):
            build_lot(db, brand.id, category.id, total_pieces=50, min_order_pieces=80)
        db.rollback()

    def test_derived_prices(self, db: Session, two_brands, category) -> None:  # type: ignore[no-untyped-def]
        (brand, _), _ = two_brands
        lot = build_lot(
            db,
            brand.id,
            category.id,
            total_pieces=100,
            retail_price_per_piece_pkr=1_000,
            lot_price_pkr=20_000,
        )
        db.commit()

        assert lot.price_per_piece_pkr == 200
        assert lot.discount_percent == 80.0


class TestOrderArithmetic:
    def _order(self, brand_id: str, lot_id: str, buyer_id: str, **overrides: object) -> Order:
        defaults: dict[str, object] = {
            "order_code": "ORD-TEST",
            "lot_id": lot_id,
            "brand_id": brand_id,
            "buyer_user_id": buyer_id,
            "pieces": 10,
            "unit_price_pkr": 200,
            "subtotal_pkr": 2_000,
            "shipping_pkr": 500,
            "total_pkr": 2_500,
            "commission_percent": 15,
            "commission_pkr": 300,
            "brand_payout_pkr": 1_700,
            "status": OrderStatus.CREATED,
            "delivery_city": "Multan",
            "delivery_address": "Shop 12",
            "delivery_phone": "03001234567",
        }
        defaults.update(overrides)
        return Order(**defaults)  # type: ignore[arg-type]

    def test_a_consistent_order_is_accepted(self, db: Session, two_brands, category) -> None:  # type: ignore[no-untyped-def]
        (brand, owner), _ = two_brands
        lot = build_lot(db, brand.id, category.id, min_order_pieces=10)
        db.commit()

        db.add(self._order(brand.id, lot.id, owner.id))
        db.commit()

        from sqlalchemy import select

        stored = db.scalars(select(Order)).one()
        assert stored.total_pkr == stored.subtotal_pkr + stored.shipping_pkr
        assert stored.brand_payout_pkr == stored.subtotal_pkr - stored.commission_pkr

    @pytest.mark.parametrize(
        "broken",
        [
            {"subtotal_pkr": 9_999},
            {"total_pkr": 1},
            {"brand_payout_pkr": 2_000},
        ],
    )
    def test_inconsistent_totals_are_refused(
        self, db: Session, two_brands, category, broken: dict[str, object]
    ) -> None:  # type: ignore[no-untyped-def]
        """Arithmetic is a constraint, not a convention.

        An order whose totals do not add up is a dispute with a brand, so no
        code path is allowed to persist one.
        """
        (brand, owner), _ = two_brands
        lot = build_lot(db, brand.id, category.id, min_order_pieces=10)
        db.commit()

        db.add(self._order(brand.id, lot.id, owner.id, **broken))
        with pytest.raises(IntegrityError):
            db.commit()
        db.rollback()


class TestPolicyIsData:
    def test_the_approval_gate_cannot_be_switched_off(self, db: Session, two_brands) -> None:  # type: ignore[no-untyped-def]
        """A brand may set its own terms, but not remove its own protection.

        Every other policy field is freely configurable. This one is pinned by
        a check constraint, because a listing going live without approval is
        the failure that would cost the platform its brands.
        """
        (brand, _), _ = two_brands
        policy = brand.policy
        policy.require_brand_approval = False
        with pytest.raises(IntegrityError):
            db.commit()
        db.rollback()

    def test_the_discount_band_must_be_ordered(self, db: Session, two_brands) -> None:  # type: ignore[no-untyped-def]
        (brand, _), _ = two_brands
        brand.policy.min_discount_percent = 90
        brand.policy.max_discount_percent = 40
        with pytest.raises(IntegrityError):
            db.commit()
        db.rollback()


class TestSeed:
    def test_the_seed_produces_a_usable_marketplace(self, engine) -> None:  # type: ignore[no-untyped-def]
        from sqlalchemy.orm import Session as SASession

        from khazana.seed import seed

        with SASession(engine) as session:
            counts = seed(session, scale=1)

        assert counts["brands"] == 5
        assert counts["lots"] > 0
        assert counts["orders"] > 0
        assert counts["resellers"] == 12

    def test_every_seeded_lot_has_a_balanced_manifest(self, engine) -> None:  # type: ignore[no-untyped-def]
        """The seed must obey the platform's own rules.

        Seed data that breaks an invariant is worse than no seed data: it
        teaches the whole team that the invariant is optional.
        """
        from sqlalchemy import select
        from sqlalchemy.orm import Session as SASession

        from khazana.seed import seed

        with SASession(engine) as session:
            seed(session, scale=1)
            lots = session.scalars(select(Lot)).all()
            assert lots
            unbalanced = [lot.lot_code for lot in lots if not lot.is_manifest_balanced]
            assert not unbalanced, f"unbalanced seeded lots: {unbalanced}"

    def test_seeded_live_lots_are_all_approved(self, engine) -> None:  # type: ignore[no-untyped-def]
        from sqlalchemy import select
        from sqlalchemy.orm import Session as SASession

        from khazana.seed import seed

        with SASession(engine) as session:
            seed(session, scale=1)
            live = session.scalars(select(Lot).where(Lot.status == LotStatus.LIVE)).all()
            assert live
            assert all(lot.approved_at is not None for lot in live)

class TestEnumRoundTrip:
    """Enum columns must come back as enums, not as bare strings.

    This was a real bug. A ``Mapped[ConditionGrade]`` column declared with an
    explicit ``String`` stores the value correctly and hands back a plain
    ``str`` on the next load. Comparisons keep working, because a StrEnum
    equals its own value, so nothing fails until some code calls ``.value``
    and raises an AttributeError on a product page.

    It survived the first hundred tests because objects were still in the
    identity map with the Python enum attached. It only appeared once a lot
    was committed and read back in a fresh query.
    """

    def test_a_lot_reloaded_from_the_database_keeps_its_enums(
        self, db: Session, two_brands, category
    ) -> None:  # type: ignore[no-untyped-def]
        from sqlalchemy import select

        from khazana.models.enums import Visibility

        (brand, _), _ = two_brands
        lot = build_lot(db, brand.id, category.id)
        db.commit()
        lot_id = lot.id

        # A new session, so nothing is served from the identity map.
        db.expunge_all()
        reloaded = db.scalars(select(Lot).where(Lot.id == lot_id)).one()

        assert isinstance(reloaded.condition_grade, ConditionGrade)
        assert isinstance(reloaded.status, LotStatus)
        assert isinstance(reloaded.visibility, Visibility)
        # The call that used to raise.
        assert reloaded.condition_grade.value == "A"

    def test_every_enum_column_uses_the_coercing_type(self) -> None:
        """Catch a new enum column declared with a bare String.

        A future model that writes mapped_column(String(16)) for an enum
        re-introduces exactly this bug, and nothing else would notice.
        """
        from khazana.models import Base
        from khazana.models.base import EnumText

        offenders = []
        for table in Base.metadata.tables.values():
            for column in table.columns:
                # A column whose default is a StrEnum member is an enum
                # column, so its type must coerce on the way back out.
                default = column.default
                arg = getattr(default, "arg", None) if default is not None else None
                if isinstance(arg, StrEnum) and not isinstance(column.type, EnumText):
                    offenders.append(f"{table.name}.{column.name}")

        assert not offenders, (
            "these enum columns are stored as plain strings and will come back "
            f"as str: {offenders}"
        )
