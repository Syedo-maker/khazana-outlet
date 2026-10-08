"""Tenant isolation.

This is the most important test file in the repository. In a marketplace where
competing brands list stock on the same platform, one leak between two brands
ends the business, so these tests are written to fail loudly rather than to
pass quietly.
"""

from __future__ import annotations

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from khazana.api.deps import Principal
from khazana.core.errors import CrossTenant
from khazana.core.tenancy import assert_owns, scoped
from khazana.models import BRAND_SCOPED_TABLES, Base, Lot, ManifestLine
from khazana.models.enums import ConditionGrade, LotStatus, UserRole, Visibility


def make_lot(db: Session, brand_id: str, category_id: str, code: str) -> Lot:
    lot = Lot(
        lot_code=code,
        brand_id=brand_id,
        category_id=category_id,
        title="Test lot",
        condition_grade=ConditionGrade.A,
        total_pieces=100,
        retail_price_per_piece_pkr=1000,
        lot_price_pkr=25_000,
        min_order_pieces=100,
        stock_city="Lahore",
        status=LotStatus.DRAFT,
        visibility=Visibility.PRIVATE,
    )
    db.add(lot)
    db.flush()
    db.add(ManifestLine(lot_id=lot.id, brand_id=brand_id, size="M", color="black", pieces=100))
    db.commit()
    return lot


class TestSchemaInvariants:
    def test_every_brand_scoped_table_actually_has_a_brand_id(self) -> None:
        """The list in models/__init__.py must stay true.

        If a table is added to BRAND_SCOPED_TABLES without a brand_id column,
        the row level policy in migration 0001 would fail to create. This
        catches that at test time rather than at deploy time.
        """
        for name in BRAND_SCOPED_TABLES:
            table = Base.metadata.tables[name]
            assert "brand_id" in table.c, f"{name} is listed as brand scoped but has no brand_id"

    def test_no_brand_owned_table_is_missing_from_the_list(self) -> None:
        """Catch a new table that has a brand_id but was never registered.

        Without this, a Phase 3 table could be added with a brand_id and no
        isolation policy, and nothing would complain.
        """
        with_brand_id = {
            name for name, table in Base.metadata.tables.items() if "brand_id" in table.c
        }
        # These legitimately carry a nullable brand_id but are not tenant
        # owned rows: they are platform records that reference a brand.
        allowed_extras = {"brands", "ai_jobs", "ai_spend", "embeddings", "audit_log"}
        unregistered = with_brand_id - set(BRAND_SCOPED_TABLES) - allowed_extras
        assert not unregistered, (
            f"These tables have a brand_id but are not in BRAND_SCOPED_TABLES: "
            f"{sorted(unregistered)}. Add them, or add them to allowed_extras "
            f"with a reason."
        )


class TestScopedQueries:
    def test_a_brand_sees_only_its_own_lots(self, db: Session, two_brands, category) -> None:  # type: ignore[no-untyped-def]
        (brand_one, owner_one), (brand_two, _owner_two) = two_brands
        make_lot(db, brand_one.id, category.id, "LOT-1")
        make_lot(db, brand_two.id, category.id, "LOT-2")

        principal = Principal(user_id=owner_one.id, role=UserRole.BRAND, brand_ids=[brand_one.id])
        visible = db.scalars(scoped(select(Lot), Lot, principal)).all()

        assert [lot.lot_code for lot in visible] == ["LOT-1"]

    def test_admin_sees_everything(self, db: Session, two_brands, category, admin_user) -> None:  # type: ignore[no-untyped-def]
        (brand_one, _), (brand_two, _) = two_brands
        make_lot(db, brand_one.id, category.id, "LOT-1")
        make_lot(db, brand_two.id, category.id, "LOT-2")

        principal = Principal(user_id=admin_user.id, role=UserRole.ADMIN, brand_ids=[])
        visible = db.scalars(scoped(select(Lot), Lot, principal)).all()

        assert len(visible) == 2

    def test_a_brand_user_with_no_membership_sees_nothing(
        self, db: Session, two_brands, category
    ) -> None:  # type: ignore[no-untyped-def]
        """The failure mode this guards against is the dangerous one.

        A naive implementation that skips the filter when the membership list
        is empty would return every brand's lots to a user who belongs to no
        brand at all.
        """
        (brand_one, _), _ = two_brands
        make_lot(db, brand_one.id, category.id, "LOT-1")

        principal = Principal(user_id="ghost", role=UserRole.BRAND, brand_ids=[])
        assert db.scalars(scoped(select(Lot), Lot, principal)).all() == []

    def test_a_reseller_sees_nothing_through_the_ownership_path(
        self, db: Session, two_brands, category
    ) -> None:  # type: ignore[no-untyped-def]
        (brand_one, _), _ = two_brands
        make_lot(db, brand_one.id, category.id, "LOT-1")

        principal = Principal(user_id="buyer", role=UserRole.RESELLER, brand_ids=[])
        assert db.scalars(scoped(select(Lot), Lot, principal)).all() == []

    def test_multi_brand_user_sees_both(self, db: Session, two_brands, category) -> None:  # type: ignore[no-untyped-def]
        (brand_one, owner_one), (brand_two, _) = two_brands
        make_lot(db, brand_one.id, category.id, "LOT-1")
        make_lot(db, brand_two.id, category.id, "LOT-2")

        principal = Principal(
            user_id=owner_one.id,
            role=UserRole.BRAND,
            brand_ids=[brand_one.id, brand_two.id],
        )
        visible = db.scalars(scoped(select(Lot), Lot, principal)).all()
        assert {lot.lot_code for lot in visible} == {"LOT-1", "LOT-2"}

    def test_manifest_lines_are_scoped_too(self, db: Session, two_brands, category) -> None:  # type: ignore[no-untyped-def]
        """Child rows must be filterable without joining the parent."""
        (brand_one, owner_one), (brand_two, _) = two_brands
        make_lot(db, brand_one.id, category.id, "LOT-1")
        make_lot(db, brand_two.id, category.id, "LOT-2")

        principal = Principal(user_id=owner_one.id, role=UserRole.BRAND, brand_ids=[brand_one.id])
        lines = db.scalars(scoped(select(ManifestLine), ManifestLine, principal)).all()
        assert len(lines) == 1
        assert lines[0].brand_id == brand_one.id


class TestOwnershipAssertion:
    def test_owner_passes(self, two_brands) -> None:  # type: ignore[no-untyped-def]
        (brand_one, owner_one), _ = two_brands
        principal = Principal(user_id=owner_one.id, role=UserRole.BRAND, brand_ids=[brand_one.id])
        assert_owns(principal, brand_one.id)

    def test_stranger_is_told_it_does_not_exist(self, two_brands) -> None:  # type: ignore[no-untyped-def]
        """A cross tenant read reports 404, not 403.

        Answering 403 would confirm that the record exists and belongs to
        someone else, which is itself a leak.
        """
        (brand_one, owner_one), (brand_two, _) = two_brands
        principal = Principal(user_id=owner_one.id, role=UserRole.BRAND, brand_ids=[brand_one.id])
        with pytest.raises(CrossTenant) as caught:
            assert_owns(principal, brand_two.id)
        assert caught.value.status_code == 404

    def test_admin_bypasses(self, two_brands, admin_user) -> None:  # type: ignore[no-untyped-def]
        _, (brand_two, _) = two_brands
        principal = Principal(user_id=admin_user.id, role=UserRole.ADMIN, brand_ids=[])
        assert_owns(principal, brand_two.id)

    def test_a_null_brand_id_is_not_a_free_pass(self, two_brands) -> None:  # type: ignore[no-untyped-def]
        (brand_one, owner_one), _ = two_brands
        principal = Principal(user_id=owner_one.id, role=UserRole.BRAND, brand_ids=[brand_one.id])
        with pytest.raises(CrossTenant):
            assert_owns(principal, None)
