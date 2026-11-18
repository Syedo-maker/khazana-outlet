"""Buyer search: filters, sorting, keywords, meaning and photographs.

Every path ends in `approval_service.visibility_filter`, including the vector
paths, whose raw results are only candidates. That is what keeps private lots
and region locked stock out of search.

The search text never includes the brand name, so an unbranded lot cannot be
found by typing the brand it came from.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import ColumnElement, Float, Select, cast, func, or_, select
from sqlalchemy.orm import Session, selectinload

from ..ai import embeddings, images
from ..core.errors import Conflict, NotFound, ValidationFailed
from ..models import Category, Lot, SavedSearch, User
from ..models.base import utcnow
from ..models.enums import ConditionGrade, UserRole
from . import approval_service

MAX_QUERY_TERMS = 8
# Vector matches are filtered afterwards, so more are fetched than one page.
VECTOR_CANDIDATES = 200
# Below this, a photograph match is closer to noise than to the same product.
MIN_PHOTO_SIMILARITY = 0.6
MAX_SAVED_SEARCHES = 25

METHOD_ALL = "all"
METHOD_KEYWORD = "keyword"
METHOD_SEMANTIC = "semantic"
METHOD_PHOTO = "photo"


@dataclass(frozen=True, slots=True)
class SearchFilters:
    q: str | None = None
    mode: str = "auto"
    category_id: str | None = None
    stock_city: str | None = None
    grades: tuple[ConditionGrade, ...] = ()
    season: str | None = None
    min_price_per_piece_pkr: int | None = None
    max_price_per_piece_pkr: int | None = None
    min_lot_price_pkr: int | None = None
    max_lot_price_pkr: int | None = None
    min_discount_percent: float | None = None
    min_pieces: int | None = None
    max_pieces: int | None = None
    sort: str = "newest"


@dataclass(frozen=True, slots=True)
class Viewer:
    role: UserRole | None
    verified: bool
    city: str | None


@dataclass(slots=True)
class SearchResult:
    lots: list[Lot]
    total: int
    method: str
    note: str | None = None
    similarity: dict[str, float] = field(default_factory=dict)


def _price_per_piece() -> ColumnElement[Any]:
    return cast(Lot.lot_price_pkr, Float) / Lot.total_pieces


def _discount_ratio() -> ColumnElement[Any]:
    return cast(Lot.lot_price_pkr, Float) / (Lot.retail_price_per_piece_pkr * Lot.total_pieces)


SORTS: dict[str, Callable[[], ColumnElement[Any]]] = {
    "newest": lambda: Lot.approved_at.desc(),
    "price_low": lambda: _price_per_piece().asc(),
    "price_high": lambda: _price_per_piece().desc(),
    "discount": lambda: _discount_ratio().asc(),
    "pieces": lambda: Lot.total_pieces.desc(),
}


def _like(term: str) -> str:
    escaped = term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


def _text_conditions(q: str) -> list[ColumnElement[bool]]:
    conditions: list[ColumnElement[bool]] = []
    for term in q.split()[:MAX_QUERY_TERMS]:
        pattern = _like(term)
        matching_categories = select(Category.id).where(Category.name.ilike(pattern, escape="\\"))
        conditions.append(
            or_(
                Lot.title.ilike(pattern, escape="\\"),
                Lot.description.ilike(pattern, escape="\\"),
                Lot.season.ilike(pattern, escape="\\"),
                Lot.lot_code.ilike(pattern, escape="\\"),
                Lot.category_id.in_(matching_categories),
            )
        )
    return conditions


def _filter_conditions(db: Session, filters: SearchFilters) -> list[ColumnElement[bool]]:
    conditions: list[ColumnElement[bool]] = []

    if filters.category_id:
        children = select(Category.id).where(Category.parent_id == filters.category_id)
        conditions.append(
            or_(Lot.category_id == filters.category_id, Lot.category_id.in_(children))
        )
    if filters.stock_city:
        conditions.append(func.lower(Lot.stock_city) == filters.stock_city.casefold())
    if filters.grades:
        conditions.append(Lot.condition_grade.in_(filters.grades))
    if filters.season:
        conditions.append(Lot.season.ilike(_like(filters.season), escape="\\"))

    # Whole number comparisons, so a rounded price never decides a match.
    if filters.min_price_per_piece_pkr is not None:
        conditions.append(Lot.lot_price_pkr >= filters.min_price_per_piece_pkr * Lot.total_pieces)
    if filters.max_price_per_piece_pkr is not None:
        conditions.append(Lot.lot_price_pkr <= filters.max_price_per_piece_pkr * Lot.total_pieces)
    if filters.min_lot_price_pkr is not None:
        conditions.append(Lot.lot_price_pkr >= filters.min_lot_price_pkr)
    if filters.max_lot_price_pkr is not None:
        conditions.append(Lot.lot_price_pkr <= filters.max_lot_price_pkr)
    if filters.min_discount_percent is not None:
        conditions.append(_discount_ratio() <= 1 - filters.min_discount_percent / 100)
    if filters.min_pieces is not None:
        conditions.append(Lot.total_pieces >= filters.min_pieces)
    if filters.max_pieces is not None:
        conditions.append(Lot.total_pieces <= filters.max_pieces)
    return conditions


def _visibility(viewer: Viewer) -> ColumnElement[bool]:
    return approval_service.visibility_filter(
        role=viewer.role, reseller_is_verified=viewer.verified, city=viewer.city
    )


def _with_listing_data(statement: Select[Any]) -> Select[Any]:
    return statement.options(selectinload(Lot.photos), selectinload(Lot.manifest_lines))


def search(
    db: Session,
    *,
    filters: SearchFilters,
    viewer: Viewer,
    limit: int = 24,
    offset: int = 0,
) -> SearchResult:
    query = (filters.q or "").strip()
    note: str | None = None

    if query and filters.mode != "keyword":
        vector_ready = embeddings.supports_similarity(db)
        real_model = not isinstance(embeddings.get_provider(), embeddings.HashingProvider)
        if filters.mode == "semantic" and not vector_ready:
            note = "Search by meaning needs PostgreSQL here, so keywords were used."
        elif vector_ready and (real_model or filters.mode == "semantic"):
            return _vector_text_search(db, query, filters, viewer, limit, offset, real_model)

    conditions = [_visibility(viewer), *_filter_conditions(db, filters)]
    if query:
        conditions.extend(_text_conditions(query))

    total = db.scalar(select(func.count()).select_from(Lot).where(*conditions)) or 0
    order = SORTS.get(filters.sort, SORTS["newest"])()
    rows = db.scalars(
        _with_listing_data(select(Lot).where(*conditions))
        .order_by(order, Lot.id)
        .limit(limit)
        .offset(offset)
    ).all()
    return SearchResult(
        lots=list(rows),
        total=int(total),
        method=METHOD_KEYWORD if query else METHOD_ALL,
        note=note,
    )


def _ranked_visible(
    db: Session,
    ranked: dict[str, float],
    filters: SearchFilters,
    viewer: Viewer,
) -> list[Lot]:
    if not ranked:
        return []
    rows = db.scalars(
        _with_listing_data(
            select(Lot).where(
                Lot.id.in_(ranked),
                _visibility(viewer),
                *_filter_conditions(db, filters),
            )
        )
    ).all()
    return sorted(rows, key=lambda lot: ranked[lot.id], reverse=True)


def _vector_text_search(
    db: Session,
    query: str,
    filters: SearchFilters,
    viewer: Viewer,
    limit: int,
    offset: int,
    real_model: bool,
) -> SearchResult:
    hits = embeddings.search_by_text(
        db,
        query,
        limit=VECTOR_CANDIDATES,
        exclude_private=not viewer.verified,
    )
    ranked = {hit.lot.id: hit.similarity for hit in hits}
    lots = _ranked_visible(db, ranked, filters, viewer)
    return SearchResult(
        lots=lots[offset : offset + limit],
        total=len(lots),
        method=METHOD_SEMANTIC,
        note=None if real_model else "The embedding service is a development stand in.",
        similarity={lot.id: round(ranked[lot.id], 3) for lot in lots},
    )


def search_by_photo(
    db: Session,
    *,
    data: bytes,
    filters: SearchFilters,
    viewer: Viewer,
    limit: int = 24,
    offset: int = 0,
) -> SearchResult:
    """Find lots that look like a photograph.

    The query goes through the same preparation as stored photographs. Unbranded
    lots are left out entirely, so a logo cannot be used to unmask them.
    """
    if not embeddings.supports_similarity(db):
        raise Conflict("Photo search needs PostgreSQL with pgvector.")
    try:
        prepared = images.prepare(data).data
    except images.ImageError as exc:
        raise ValidationFailed(str(exc)) from exc

    # The stand in hashes exact bytes. A stored photograph that is uploaded again
    # only matches as it is, because preparing it a second time changes them.
    stand_in = isinstance(embeddings.get_provider(), embeddings.HashingProvider)
    queries = [prepared, data] if stand_in and data != prepared else [prepared]

    ranked: dict[str, float] = {}
    for query_image in queries:
        hits = embeddings.search_by_image(
            db,
            query_image,
            limit=VECTOR_CANDIDATES,
            exclude_private=not viewer.verified,
            exclude_unbranded=True,
        )
        for hit in hits:
            if hit.similarity >= MIN_PHOTO_SIMILARITY:
                ranked[hit.lot.id] = max(hit.similarity, ranked.get(hit.lot.id, 0.0))

    lots = _ranked_visible(db, ranked, filters, viewer)
    return SearchResult(
        lots=lots[offset : offset + limit],
        total=len(lots),
        method=METHOD_PHOTO,
        note="The development stand in only finds the same photograph." if stand_in else None,
        similarity={lot.id: round(ranked[lot.id], 3) for lot in lots},
    )


# ------------------------------------------------------------- saved searches


def list_saved(db: Session, *, user: User) -> list[SavedSearch]:
    return list(
        db.scalars(
            select(SavedSearch)
            .where(SavedSearch.user_id == user.id)
            .order_by(SavedSearch.created_at.desc())
        ).all()
    )


def save(db: Session, *, user: User, name: str, filters: dict[str, object]) -> SavedSearch:
    existing = list_saved(db, user=user)
    cleaned = " ".join(name.split())
    if not cleaned:
        raise ValidationFailed("Give this search a name.")
    if any(row.name.casefold() == cleaned.casefold() for row in existing):
        raise Conflict("You already have a saved search with that name.")
    if len(existing) >= MAX_SAVED_SEARCHES:
        raise Conflict(f"You can keep up to {MAX_SAVED_SEARCHES} saved searches.")

    row = SavedSearch(user_id=user.id, name=cleaned, filters=filters, last_run_at=utcnow())
    db.add(row)
    db.flush()
    return row


def get_saved(db: Session, *, user: User, saved_id: str) -> SavedSearch:
    row = db.get(SavedSearch, saved_id)
    if row is None or row.user_id != user.id:
        raise NotFound("That saved search does not exist.")
    return row


def count_new_matches(
    db: Session, *, saved: SavedSearch, filters: SearchFilters, viewer: Viewer
) -> int:
    """Listings matching this search that went live since it was last opened."""
    conditions = [_visibility(viewer), *_filter_conditions(db, filters)]
    if filters.q:
        conditions.extend(_text_conditions(filters.q))
    if saved.last_run_at is not None:
        conditions.append(Lot.approved_at > saved.last_run_at)
    return int(db.scalar(select(func.count()).select_from(Lot).where(*conditions)) or 0)
