"""Vector search against real PostgreSQL with pgvector.

Everything in this file is the part of search that SQLite cannot test: the
cosine ranking, the visibility filter and the brand exclusion all run inside
one SQL statement, and a statement that is never executed is a statement that
is never proved.

These tests run when ``TEST_DATABASE_URL`` points at PostgreSQL, which CI sets
for the database job. Locally they skip with a visible reason rather than
pretending to pass.
"""

from __future__ import annotations

import os

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session, sessionmaker

from khazana.ai import embeddings
from khazana.models import Base, Brand, BrandPolicy, Category, Lot, User
from khazana.models.base import utcnow
from khazana.models.enums import (
    ConditionGrade,
    LotStatus,
    UserRole,
    VerificationStatus,
    Visibility,
)

PG_URL = os.environ.get("TEST_DATABASE_URL", "")

pytestmark = pytest.mark.skipif(
    not PG_URL.startswith("postgresql"),
    reason="needs PostgreSQL with pgvector, set TEST_DATABASE_URL to run",
)


@pytest.fixture
def pg_session():  # type: ignore[no-untyped-def]
    from khazana.db import build_engine

    engine = build_engine(PG_URL)
    with engine.begin() as connection:
        connection.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))

    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)

    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    session = factory()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(engine)
        engine.dispose()


def seed_brand(db: Session, *, name: str, slug: str, phone: str) -> Brand:
    owner = User(phone=phone, full_name=f"{name} owner", role=UserRole.BRAND)
    db.add(owner)
    db.flush()
    brand = Brand(name=name, slug=slug, city="Lahore", status=VerificationStatus.VERIFIED)
    db.add(brand)
    db.flush()
    db.add(BrandPolicy(brand_id=brand.id))
    db.commit()
    return brand


def seed_lot(
    db: Session,
    brand: Brand,
    category: Category,
    *,
    code: str,
    title: str,
    status: LotStatus = LotStatus.LIVE,
    visibility: Visibility = Visibility.PUBLIC,
    approved: bool = True,
) -> Lot:
    lot = Lot(
        lot_code=code,
        brand_id=brand.id,
        category_id=category.id,
        title=title,
        description=title,
        condition_grade=ConditionGrade.A,
        total_pieces=50,
        retail_price_per_piece_pkr=2_000,
        lot_price_pkr=30_000,
        min_order_pieces=50,
        stock_city="Lahore",
        status=status,
        visibility=visibility,
        approved_at=utcnow() if approved else None,
    )
    db.add(lot)
    db.commit()
    embeddings.index_lot(db, lot, category_name=category.name)
    db.commit()
    return lot


@pytest.fixture
def world(pg_session: Session):  # type: ignore[no-untyped-def]
    embeddings.reset_provider()
    category = Category(name="Womenswear stitched", slug="womenswear-stitched")
    pg_session.add(category)
    pg_session.commit()

    first = seed_brand(pg_session, name="Brand One", slug="brand-one", phone="03001111111")
    second = seed_brand(pg_session, name="Brand Two", slug="brand-two", phone="03002222222")

    lots = {
        "lawn": seed_lot(
            pg_session, first, category, code="LOT-LAWN", title="printed lawn suits summer"
        ),
        "chairs": seed_lot(
            pg_session, first, category, code="LOT-CHAIR", title="leather office chairs bulk"
        ),
        "draft": seed_lot(
            pg_session,
            first,
            category,
            code="LOT-DRAFT",
            title="printed lawn suits summer",
            status=LotStatus.DRAFT,
            approved=False,
        ),
        "private": seed_lot(
            pg_session,
            first,
            category,
            code="LOT-PRIV",
            title="printed lawn suits summer",
            visibility=Visibility.PRIVATE,
        ),
        "other_brand": seed_lot(
            pg_session, second, category, code="LOT-OTHER", title="printed lawn suits summer"
        ),
    }
    yield pg_session, first, second, lots
    embeddings.reset_provider()


class TestSimilarityRanking:
    def test_the_closest_wording_ranks_first(self, world) -> None:  # type: ignore[no-untyped-def]
        db, _first, _second, _lots = world

        hits = embeddings.search_by_text(db, "printed lawn suits summer", limit=10)

        assert hits, "expected at least one hit"
        assert hits[0].lot.lot_code in {"LOT-LAWN", "LOT-OTHER"}
        assert hits[0].similarity > 0.9

        codes = [hit.lot.lot_code for hit in hits]
        assert codes.index("LOT-LAWN") < codes.index("LOT-CHAIR")

    def test_distance_is_reported_as_a_readable_similarity(self, world) -> None:  # type: ignore[no-untyped-def]
        db, _first, _second, _lots = world
        hits = embeddings.search_by_text(db, "printed lawn suits summer", limit=3)
        for hit in hits:
            assert 0.0 <= hit.similarity <= 1.0


class TestVisibilityFilter:
    def test_a_draft_lot_never_appears(self, world) -> None:  # type: ignore[no-untyped-def]
        """The leak this filter exists to prevent.

        A draft has not been approved by its brand, so showing it to a buyer
        breaks the one promise the platform makes to brands.
        """
        db, _first, _second, _lots = world
        codes = {
            hit.lot.lot_code for hit in embeddings.search_by_text(db, "printed lawn", limit=20)
        }
        assert "LOT-DRAFT" not in codes

    def test_a_private_lot_is_not_in_general_search(self, world) -> None:  # type: ignore[no-untyped-def]
        db, _first, _second, _lots = world
        codes = {
            hit.lot.lot_code for hit in embeddings.search_by_text(db, "printed lawn", limit=20)
        }
        assert "LOT-PRIV" not in codes

    def test_a_soft_deleted_lot_is_not_returned(self, world) -> None:  # type: ignore[no-untyped-def]
        db, _first, _second, lots = world
        lots["lawn"].deleted_at = utcnow()
        db.commit()

        codes = {
            hit.lot.lot_code for hit in embeddings.search_by_text(db, "printed lawn", limit=20)
        }
        assert "LOT-LAWN" not in codes

    def test_visible_only_can_be_turned_off_for_admin_use(self, world) -> None:  # type: ignore[no-untyped-def]
        db, _first, _second, _lots = world
        codes = {
            hit.lot.lot_code
            for hit in embeddings.search_by_text(db, "printed lawn", limit=20, visible_only=False)
        }
        assert "LOT-DRAFT" in codes


class TestBrandExclusion:
    def test_a_brand_is_not_shown_its_own_lots_when_excluded(self, world) -> None:  # type: ignore[no-untyped-def]
        """Used when a brand looks for comparable lots.

        A brand must not be shown another brand's stock in a brand facing
        view, and it gains nothing from being shown its own.
        """
        db, first, _second, _lots = world

        hits = embeddings.search_by_text(
            db, "printed lawn suits summer", limit=20, exclude_brand_id=first.id
        )
        brand_ids = {hit.lot.brand_id for hit in hits}

        assert first.id not in brand_ids
        assert hits, "the other brand's lot should still be reachable"


class TestDimensionSafety:
    def test_vectors_from_another_model_are_ignored(self, world) -> None:  # type: ignore[no-untyped-def]
        """Mixing models returns nonsense, not an error, so the query filters.

        This is the failure that produces confident rubbish rather than a
        stack trace, which is why it is filtered in SQL and proved here.
        """
        db, _first, _second, _lots = world

        db.execute(
            text(
                "UPDATE embeddings SET model = 'some-other-model' "
                "WHERE owner_id = (SELECT id FROM lots WHERE lot_code = 'LOT-LAWN')"
            )
        )
        db.commit()

        codes = {
            hit.lot.lot_code for hit in embeddings.search_by_text(db, "printed lawn", limit=20)
        }
        assert "LOT-LAWN" not in codes
