"""Embeddings and search.

The search path is built and tested here; the semantic quality of the vectors
is a property of whichever model is configured, and the default provider is
explicitly not semantic. These tests therefore check the things that are
actually this codebase's responsibility: determinism, dimension safety,
indexing, and the two filters that must never be forgotten.

Similarity search itself needs PostgreSQL. Those tests are skipped on SQLite
and covered by the migration job in CI, and the skip is visible rather than a
silent pass.
"""

from __future__ import annotations

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from khazana.ai import embeddings
from khazana.models import Category, Embedding, Lot
from khazana.models.enums import ConditionGrade, EmbeddingOwner, LotStatus, Visibility


@pytest.fixture(autouse=True)
def fresh_provider():  # type: ignore[no-untyped-def]
    embeddings.reset_provider()
    yield
    embeddings.reset_provider()


@pytest.fixture
def category(db: Session) -> Category:
    row = Category(name="Womenswear stitched", slug="womenswear-stitched")
    db.add(row)
    db.commit()
    return row


def make_lot(db: Session, brand_id: str, category_id: str, **overrides: object) -> Lot:
    defaults: dict[str, object] = {
        "lot_code": "LOT-E1",
        "brand_id": brand_id,
        "category_id": category_id,
        "title": "Printed lawn three piece suits",
        "description": "Summer surplus, tags attached.",
        "season": "Summer 2026",
        "condition_grade": ConditionGrade.A,
        "total_pieces": 100,
        "retail_price_per_piece_pkr": 2_000,
        "lot_price_pkr": 50_000,
        "min_order_pieces": 100,
        "stock_city": "Lahore",
        "status": LotStatus.DRAFT,
        "visibility": Visibility.PUBLIC,
    }
    defaults.update(overrides)
    lot = Lot(**defaults)  # type: ignore[arg-type]
    db.add(lot)
    db.commit()
    return lot


class TestProvider:
    def test_the_default_provider_is_the_stub_and_says_so(self) -> None:
        provider = embeddings.get_provider()
        assert isinstance(provider, embeddings.HashingProvider)
        assert "stub" in provider.name

    def test_text_embedding_is_deterministic(self) -> None:
        """The same input must give the same vector.

        Without this an index would silently disagree with itself, and a lot
        re-indexed after an edit would stop matching its own photographs.
        """
        provider = embeddings.HashingProvider(dim=64)
        assert provider.embed_text("lawn suits") == provider.embed_text("lawn suits")

    def test_text_embedding_is_normalised(self) -> None:
        provider = embeddings.HashingProvider(dim=64)
        vector = provider.embed_text("printed lawn three piece")
        magnitude = sum(value * value for value in vector) ** 0.5
        assert magnitude == pytest.approx(1.0, abs=1e-9)

    def test_shared_wording_lands_closer_than_unrelated_wording(self) -> None:
        """What the stub can do, stated as a test rather than as a claim.

        It matches shared character trigrams. It does not know that kurta and
        shirt are related, and nothing in this codebase should imply it does.
        """
        provider = embeddings.HashingProvider(dim=256)

        def cosine(a: list[float], b: list[float]) -> float:
            return sum(x * y for x, y in zip(a, b, strict=True))

        base = provider.embed_text("printed lawn suits")
        near = provider.embed_text("printed lawn shirts")
        far = provider.embed_text("leather office chairs")

        assert cosine(base, near) > cosine(base, far)

    def test_an_empty_string_gives_a_zero_vector_rather_than_an_error(self) -> None:
        provider = embeddings.HashingProvider(dim=32)
        assert provider.embed_text("   ") == [0.0] * 32

    def test_image_embedding_finds_the_identical_file_only(self) -> None:
        """Honest about the limit: byte identity, not visual similarity."""
        provider = embeddings.HashingProvider(dim=64)
        assert provider.embed_image(b"photo-bytes") == provider.embed_image(b"photo-bytes")
        assert provider.embed_image(b"photo-bytes") != provider.embed_image(b"other-bytes")

    def test_the_configured_dimension_is_honoured(self) -> None:
        assert len(embeddings.HashingProvider(dim=128).embed_text("x")) == 128


class TestLotText:
    def test_the_brand_name_is_not_in_the_indexed_text(
        self, db: Session, two_brands, category
    ) -> None:  # type: ignore[no-untyped-def]
        """The protection a brand was promised must survive the search index.

        An unbranded listing that becomes findable by brand name through
        semantic search has had its protection quietly defeated, and nobody
        would notice until a brand did.
        """
        (brand, _), _ = two_brands
        lot = make_lot(db, brand.id, category.id, visibility=Visibility.UNBRANDED)

        indexed = embeddings.lot_text(lot, category_name=category.name)

        assert brand.name.lower() not in indexed.lower()
        assert "lawn" in indexed.lower()
        assert "womenswear" in indexed.lower()

    def test_empty_fields_do_not_produce_stray_spaces(
        self, db: Session, two_brands, category
    ) -> None:  # type: ignore[no-untyped-def]
        (brand, _), _ = two_brands
        lot = make_lot(db, brand.id, category.id, description=None, season=None)
        indexed = embeddings.lot_text(lot)
        assert "  " not in indexed


class TestIndexing:
    def test_indexing_a_lot_stores_model_and_dimension(
        self, db: Session, two_brands, category
    ) -> None:  # type: ignore[no-untyped-def]
        """Both are stored because mixing them returns nonsense, not an error.

        A similarity query across two embedding models or two dimensions
        produces plausible looking rubbish, so the model name and dimension
        are columns and the query filters on them.
        """
        (brand, _), _ = two_brands
        lot = make_lot(db, brand.id, category.id)

        row = embeddings.index_lot(db, lot, category_name=category.name)
        db.commit()

        assert row.model == embeddings.get_provider().name
        assert row.dim == embeddings.get_provider().dim
        assert row.lot_id == lot.id
        assert row.brand_id == brand.id
        assert len(row.vector) == row.dim

    def test_reindexing_updates_rather_than_duplicates(
        self, db: Session, two_brands, category
    ) -> None:  # type: ignore[no-untyped-def]
        (brand, _), _ = two_brands
        lot = make_lot(db, brand.id, category.id)

        embeddings.index_lot(db, lot, category_name=category.name)
        db.commit()
        first = db.scalars(select(Embedding)).one().vector

        lot.title = "Completely different wording about footwear"
        db.commit()
        embeddings.index_lot(db, lot, category_name=category.name)
        db.commit()

        rows = db.scalars(select(Embedding)).all()
        assert len(rows) == 1
        assert rows[0].vector != first

    def test_a_photo_vector_is_keyed_on_the_photo_not_the_lot(
        self, db: Session, two_brands, category
    ) -> None:  # type: ignore[no-untyped-def]
        (brand, _), _ = two_brands
        lot = make_lot(db, brand.id, category.id)

        embeddings.index_photo(db, photo_id="photo-1", lot=lot, data=b"a")
        embeddings.index_photo(db, photo_id="photo-2", lot=lot, data=b"b")
        db.commit()

        rows = db.scalars(
            select(Embedding).where(Embedding.owner_type == EmbeddingOwner.LOT_PHOTO)
        ).all()
        assert len(rows) == 2
        assert {row.owner_id for row in rows} == {"photo-1", "photo-2"}
        assert all(row.lot_id == lot.id for row in rows)


class TestSearchGuards:
    def test_sqlite_refuses_with_an_instruction_rather_than_empty_results(
        self, db: Session
    ) -> None:
        """An empty result set would look like no matches, which is a lie.

        On SQLite the vector column is JSON and cannot be searched. Returning
        nothing would be indistinguishable from a genuine miss, so the caller
        is told to fall back to keyword search instead.
        """
        assert not embeddings.supports_similarity(db)

        with pytest.raises(embeddings.EmbeddingError, match="fall back to keyword search"):
            embeddings.search_by_text(db, "lawn suits")

    def test_the_postgres_only_behaviour_has_a_real_home(self) -> None:
        """Ranking and the SQL filters are proved, not assumed.

        They cannot run on SQLite, so rather than leave a permanently skipped
        placeholder here, they live in tests/test_search_postgres.py and the
        database job in CI runs that file against real PostgreSQL on every
        push. This test only asserts the file has not quietly been deleted.
        """
        from pathlib import Path

        suite = Path(__file__).parent / "test_search_postgres.py"
        assert suite.exists(), "the PostgreSQL search suite is missing"

        body = suite.read_text(encoding="utf-8")
        for required in (
            "test_the_closest_wording_ranks_first",
            "test_a_draft_lot_never_appears",
            "test_vectors_from_another_model_are_ignored",
        ):
            assert required in body, f"{required} is no longer covered"


class TestSearchFilters:
    def test_the_visibility_filter_is_built_into_the_query(self) -> None:
        """Read the SQL rather than trusting the caller.

        Filtering visibility after the query would shrink a page of results
        and, worse, would leak an unapproved listing the day a caller forgot.
        """
        import inspect

        source = inspect.getsource(embeddings.search)
        assert "l.status = :live" in source
        assert "l.approved_at IS NOT NULL" in source
        assert "l.deleted_at IS NULL" in source

    def test_the_query_filters_on_model_and_dimension(self) -> None:
        import inspect

        source = inspect.getsource(embeddings.search)
        assert "e.model = :model" in source
        assert "e.dim = :dim" in source


class TestSimilarityScore:
    def test_cosine_distance_becomes_a_readable_score(self, db: Session) -> None:
        lot = Lot(
            lot_code="LOT-X",
            brand_id="b",
            category_id="c",
            title="x",
            condition_grade=ConditionGrade.A,
            total_pieces=1,
            retail_price_per_piece_pkr=1,
            lot_price_pkr=1,
            min_order_pieces=1,
            stock_city="Lahore",
            status=LotStatus.DRAFT,
            visibility=Visibility.PUBLIC,
        )
        assert embeddings.SearchHit(lot=lot, distance=0.0).similarity == 1.0
        assert embeddings.SearchHit(lot=lot, distance=2.0).similarity == 0.0
        assert embeddings.SearchHit(lot=lot, distance=1.0).similarity == 0.5
