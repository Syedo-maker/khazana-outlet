"""Buyer search, and the rules it must not get around."""

from __future__ import annotations

from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from catalog_helpers import BASE_LOT, build_submitted_lot, jpeg_bytes, review_photos
from khazana.ai import embeddings
from khazana.core.security import create_access_token
from khazana.models import (
    Brand,
    Category,
    Embedding,
    Lot,
    ResellerProfile,
    SavedSearch,
    User,
)
from khazana.models.base import utcnow
from khazana.models.enums import (
    ConditionGrade,
    EmbeddingOwner,
    UserRole,
    VerificationStatus,
    Visibility,
)
from khazana.services import approval_service, search_service
from khazana.services.search_service import SearchFilters, Viewer


def auth(user: User) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(user.id, user.role)}"}


@pytest.fixture
def owner(two_brands) -> tuple[Brand, User]:  # type: ignore[no-untyped-def]
    return two_brands[0]


@pytest.fixture
def reseller(db: Session) -> User:
    user = User(phone="03007777777", full_name="Shop Owner", role=UserRole.RESELLER)
    db.add(user)
    db.flush()
    db.add(
        ResellerProfile(
            user_id=user.id,
            business_name="Multan Cloth House",
            city="Multan",
            status=VerificationStatus.VERIFIED,
        )
    )
    db.commit()
    return user


def live_lot(
    db: Session,
    brand: Brand,
    user: User,
    category_id: str,
    *,
    offset: int,
    visibility: Visibility = Visibility.PUBLIC,
    **overrides: object,
) -> Lot:
    lot = build_submitted_lot(db, brand, user, category_id, offset=offset, **overrides)
    if visibility == Visibility.UNBRANDED:
        brand.unbranded_label = "Leading label"
        review_photos(db, lot, user)
    approval_service.approve(db, lot=lot, actor=user, visibility=visibility)
    db.commit()
    return lot


@pytest.fixture
def lots(db: Session, owner, category) -> dict[str, Lot]:  # type: ignore[no-untyped-def]
    brand, user = owner
    return {
        "lawn": live_lot(
            db,
            brand,
            user,
            category.id,
            offset=10,
            title="Printed lawn suits",
            season="Summer 2026",
            lot_price_pkr=30_000,
        ),
        "shirts": live_lot(
            db,
            brand,
            user,
            category.id,
            offset=20,
            title="Cotton shirts",
            condition_grade=ConditionGrade.B,
            lot_price_pkr=20_000 + 5_000,
            stock_city="Karachi",
        ),
        "shawls": live_lot(
            db,
            brand,
            user,
            category.id,
            offset=30,
            title="Wool shawls",
            lot_price_pkr=45_000,
        ),
    }


def titles(body: dict[str, object]) -> list[str]:
    return [item["lot"]["title"] for item in body["items"]]  # type: ignore[index, attr-defined]


class TestKeywordSearchAndFilters:
    def test_words_match_title_season_and_category(
        self, client: TestClient, lots, reseller: User
    ) -> None:  # type: ignore[no-untyped-def]
        get = lambda q: client.get(  # noqa: E731
            "/catalog/search", params={"q": q}, headers=auth(reseller)
        ).json()
        assert titles(get("lawn")) == ["Printed lawn suits"]
        assert titles(get("summer")) == ["Printed lawn suits"]
        assert len(titles(get("womenswear"))) == 3
        assert titles(get("cotton womenswear")) == ["Cotton shirts"]

    def test_a_percent_sign_is_only_a_character(
        self, client: TestClient, lots, reseller: User
    ) -> None:  # type: ignore[no-untyped-def]
        body = client.get("/catalog/search", params={"q": "%"}, headers=auth(reseller)).json()
        assert body["total"] == 0

    @pytest.mark.parametrize(
        ("params", "expected"),
        [
            ({"grade": "B"}, {"Cotton shirts"}),
            ({"stock_city": "karachi"}, {"Cotton shirts"}),
            ({"max_price_per_piece_pkr": 250}, {"Cotton shirts"}),
            ({"min_price_per_piece_pkr": 400}, {"Wool shawls"}),
            ({"min_lot_price_pkr": 45_000}, {"Wool shawls"}),
            ({"min_discount_percent": 70}, {"Printed lawn suits", "Cotton shirts"}),
        ],
    )
    def test_filters(self, client: TestClient, lots, reseller: User, params, expected) -> None:  # type: ignore[no-untyped-def]
        body = client.get("/catalog/search", params=params, headers=auth(reseller)).json()
        assert set(titles(body)) == expected

    def test_sorting_by_price(self, client: TestClient, lots, reseller: User) -> None:  # type: ignore[no-untyped-def]
        body = client.get(
            "/catalog/search", params={"sort": "price_low"}, headers=auth(reseller)
        ).json()
        assert titles(body) == ["Cotton shirts", "Printed lawn suits", "Wool shawls"]

    def test_a_parent_category_includes_its_children(
        self, client: TestClient, db: Session, owner, category, reseller: User
    ) -> None:  # type: ignore[no-untyped-def]
        brand, user = owner
        parent = Category(name="Clothing", slug="clothing")
        db.add(parent)
        db.flush()
        category.parent_id = parent.id
        db.commit()
        live_lot(db, brand, user, category.id, offset=40)
        body = client.get(
            "/catalog/search", params={"category_id": parent.id}, headers=auth(reseller)
        ).json()
        assert body["total"] == 1

    def test_the_search_paths_are_not_read_as_lot_ids(
        self, client: TestClient, reseller: User
    ) -> None:
        assert client.get("/catalog/search", headers=auth(reseller)).status_code == 200
        assert client.get("/catalog/categories", headers=auth(reseller)).status_code == 200


class TestProtectionHolds:
    def test_a_brand_name_does_not_find_its_unbranded_lot(
        self, client: TestClient, db: Session, owner, category, reseller: User
    ) -> None:  # type: ignore[no-untyped-def]
        brand, user = owner
        live_lot(db, brand, user, category.id, offset=50, visibility=Visibility.UNBRANDED)
        body = client.get(
            "/catalog/search", params={"q": brand.name}, headers=auth(reseller)
        ).json()
        assert body["total"] == 0

    def test_the_region_lock_applies(
        self, client: TestClient, db: Session, owner, category, reseller: User
    ) -> None:  # type: ignore[no-untyped-def]
        brand, user = owner
        lot = live_lot(db, brand, user, category.id, offset=60)
        approval_service.set_region_lock(db, lot=lot, actor=user, cities=["Multan"])
        db.commit()
        assert client.get("/catalog/search", headers=auth(reseller)).json()["total"] == 0
        response = client.get("/catalog/search", params={"city": "Quetta"}, headers=auth(reseller))
        assert response.json()["total"] == 1

    def test_a_private_lot_needs_a_verified_buyer(
        self, client: TestClient, db: Session, owner, category, reseller: User
    ) -> None:  # type: ignore[no-untyped-def]
        brand, user = owner
        live_lot(db, brand, user, category.id, offset=70, visibility=Visibility.PRIVATE)
        assert client.get("/catalog/search", headers=auth(reseller)).json()["total"] == 1

        reseller.reseller_profile.status = VerificationStatus.PENDING  # type: ignore[union-attr]
        db.commit()
        assert client.get("/catalog/search", headers=auth(reseller)).json()["total"] == 0


class TestVectorPaths:
    def test_keyword_is_used_when_meaning_search_is_unavailable(
        self, client: TestClient, lots, reseller: User
    ) -> None:  # type: ignore[no-untyped-def]
        body = client.get(
            "/catalog/search",
            params={"q": "lawn", "mode": "semantic"},
            headers=auth(reseller),
        ).json()
        assert body["method"] == "keyword"
        assert "PostgreSQL" in body["note"]

    def test_vector_matches_still_pass_the_visibility_rule(
        self, db: Session, lots, monkeypatch: pytest.MonkeyPatch
    ) -> None:  # type: ignore[no-untyped-def]
        hidden = lots["shawls"]
        approval_service.set_region_lock(
            db,
            lot=hidden,
            actor=db.scalars(select(User).where(User.role == UserRole.BRAND)).first(),
            cities=["Multan"],
        )
        db.commit()
        hits = [
            embeddings.SearchHit(lot=lots["lawn"], distance=0.1),
            embeddings.SearchHit(lot=hidden, distance=0.0),
        ]
        monkeypatch.setattr(embeddings, "supports_similarity", lambda _db: True)
        monkeypatch.setattr(embeddings, "search_by_text", lambda *a, **k: hits)

        result = search_service.search(
            db,
            filters=SearchFilters(q="anything", mode="semantic"),
            viewer=Viewer(role=UserRole.RESELLER, verified=True, city="Multan"),
        )
        assert [lot.id for lot in result.lots] == [lots["lawn"].id]
        assert result.method == "semantic"

    def test_photo_search_leaves_out_unbranded_lots(
        self, db: Session, lots, monkeypatch: pytest.MonkeyPatch
    ) -> None:  # type: ignore[no-untyped-def]
        seen: dict[str, object] = {}

        def fake(_db: Session, _data: bytes, **kwargs: object) -> list[embeddings.SearchHit]:
            seen.update(kwargs)
            return [embeddings.SearchHit(lot=lots["lawn"], distance=0.0)]

        monkeypatch.setattr(embeddings, "supports_similarity", lambda _db: True)
        monkeypatch.setattr(embeddings, "search_by_image", fake)
        result = search_service.search_by_photo(
            db,
            data=jpeg_bytes(),
            filters=SearchFilters(),
            viewer=Viewer(role=UserRole.RESELLER, verified=True, city=None),
        )
        assert seen["exclude_unbranded"] is True
        assert [lot.id for lot in result.lots] == [lots["lawn"].id]

    def test_photo_search_says_when_the_database_cannot_do_it(
        self, client: TestClient, reseller: User
    ) -> None:
        response = client.post(
            "/catalog/search/photo",
            files={"file": ("a.jpg", jpeg_bytes(), "image/jpeg")},
            headers=auth(reseller),
        )
        assert response.status_code == 409


class TestIndexing:
    def test_going_live_indexes_text_and_photographs(self, db: Session, lots) -> None:  # type: ignore[no-untyped-def]
        lot_id = lots["lawn"].id
        owners = db.scalars(select(Embedding.owner_type).where(Embedding.lot_id == lot_id)).all()
        assert owners.count(EmbeddingOwner.LOT_TEXT) == 1
        assert owners.count(EmbeddingOwner.LOT_PHOTO) == 3

    def test_an_unbranded_lots_photographs_are_not_indexed(
        self, db: Session, owner, category
    ) -> None:  # type: ignore[no-untyped-def]
        brand, user = owner
        lot = live_lot(db, brand, user, category.id, offset=80, visibility=Visibility.UNBRANDED)
        owners = db.scalars(select(Embedding.owner_type).where(Embedding.lot_id == lot.id)).all()
        assert owners == [EmbeddingOwner.LOT_TEXT]

    def test_an_index_failure_does_not_stop_a_lot_going_live(
        self, db: Session, owner, category, monkeypatch: pytest.MonkeyPatch
    ) -> None:  # type: ignore[no-untyped-def]
        brand, user = owner

        def fail(*args: object, **kwargs: object) -> None:
            raise RuntimeError("embedding service down")

        monkeypatch.setattr(embeddings, "index_lot", fail)
        lot = live_lot(db, brand, user, category.id, offset=90)
        assert lot.is_publicly_visible


class TestSavedSearches:
    def test_saving_listing_and_deleting(self, client: TestClient, reseller: User) -> None:
        created = client.post(
            "/catalog/saved-searches",
            json={"name": "Lawn under 300", "filters": {"q": "lawn", "grade": ["A"]}},
            headers=auth(reseller),
        )
        assert created.status_code == 201, created.text
        saved_id = created.json()["id"]
        rows = client.get("/catalog/saved-searches", headers=auth(reseller)).json()
        assert rows[0]["filters"]["q"] == "lawn"
        assert rows[0]["filters"]["grade"] == ["A"]

        deleted = client.delete(f"/catalog/saved-searches/{saved_id}", headers=auth(reseller))
        assert deleted.status_code == 204
        assert client.get("/catalog/saved-searches", headers=auth(reseller)).json() == []

    def test_a_duplicate_name_is_refused(self, client: TestClient, reseller: User) -> None:
        body = {"name": "Lawn", "filters": {}}
        client.post("/catalog/saved-searches", json=body, headers=auth(reseller))
        second = client.post("/catalog/saved-searches", json=body, headers=auth(reseller))
        assert second.status_code == 409

    def test_new_matches_are_counted_until_the_search_is_opened(
        self, client: TestClient, db: Session, lots, reseller: User
    ) -> None:  # type: ignore[no-untyped-def]
        created = client.post(
            "/catalog/saved-searches",
            json={"name": "Everything", "filters": {}},
            headers=auth(reseller),
        ).json()
        assert created["new_matches"] == 0

        row = db.get(SavedSearch, created["id"])
        assert row is not None
        row.last_run_at = utcnow() - timedelta(days=1)
        db.commit()

        result = client.get(
            f"/catalog/saved-searches/{row.id}/results", headers=auth(reseller)
        ).json()
        assert result["new_matches"] == 3
        assert result["total"] == 3
        listed = client.get("/catalog/saved-searches", headers=auth(reseller)).json()
        assert listed[0]["new_matches"] == 0

    def test_another_users_search_reads_as_missing(
        self, client: TestClient, db: Session, reseller: User, owner
    ) -> None:  # type: ignore[no-untyped-def]
        _, other = owner
        created = client.post(
            "/catalog/saved-searches",
            json={"name": "Mine", "filters": {}},
            headers=auth(reseller),
        ).json()
        response = client.get(
            f"/catalog/saved-searches/{created['id']}/results", headers=auth(other)
        )
        assert response.status_code == 404


def test_base_lot_is_used_unchanged() -> None:
    """The price filters above depend on these numbers."""
    assert BASE_LOT["total_pieces"] == 100
