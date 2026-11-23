"""Buyer search and discovery.

Registered before the catalog router, so that `/catalog/search` is not read as
a lot identifier by `/catalog/{lot_id}`.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any, Literal

from fastapi import APIRouter, File, Query, UploadFile, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from ...core.errors import NotFound
from ...models import Category, Lot, SavedSearch, User
from ...models.base import utcnow
from ...models.enums import ConditionGrade
from ...services import (
    approval_service,
    mixed_lot_service,
    recommendation_service,
    search_service,
)
from ...services.search_service import SearchFilters, SearchResult, Viewer
from ..deps import CurrentPrincipal, Db, Principal
from .catalog import BrowseItemOut, _browse_item, _buyer_view

router = APIRouter(prefix="/catalog", tags=["search"])


class SearchParams(BaseModel):
    model_config = ConfigDict(extra="forbid")

    q: str | None = Field(default=None, max_length=200)
    mode: Literal["auto", "keyword", "semantic"] = "auto"
    category_id: str | None = None
    city: str | None = Field(default=None, max_length=80)
    stock_city: str | None = Field(default=None, max_length=80)
    grade: list[ConditionGrade] = Field(default_factory=list, max_length=3)
    season: str | None = Field(default=None, max_length=40)
    min_price_per_piece_pkr: int | None = Field(default=None, ge=0)
    max_price_per_piece_pkr: int | None = Field(default=None, ge=0)
    min_lot_price_pkr: int | None = Field(default=None, ge=0)
    max_lot_price_pkr: int | None = Field(default=None, ge=0)
    min_discount_percent: float | None = Field(default=None, ge=0, le=100)
    min_pieces: int | None = Field(default=None, ge=0)
    max_pieces: int | None = Field(default=None, ge=0)
    sort: Literal["newest", "price_low", "price_high", "discount", "pieces"] = "newest"


class SearchQuery(SearchParams):
    """The filters plus paging, read from one query string."""

    limit: int = Field(default=24, ge=1, le=100)
    offset: int = Field(default=0, ge=0)


class SearchItemOut(BrowseItemOut):
    similarity: float | None = None


class SearchOut(BaseModel):
    items: list[SearchItemOut]
    total: int
    limit: int
    offset: int
    method: str
    note: str | None = None


class CategoryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    parent_id: str | None = None
    name: str
    slug: str
    requires_expiry: bool


class SavedSearchIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=80)
    filters: SearchParams


class SavedSearchOut(BaseModel):
    id: str
    name: str
    filters: SearchParams
    last_run_at: datetime | None
    new_matches: int


class SavedSearchRunOut(SearchOut):
    new_matches: int


def _filters(params: SearchParams) -> SearchFilters:
    return SearchFilters(
        q=params.q,
        mode=params.mode,
        category_id=params.category_id,
        stock_city=params.stock_city,
        grades=tuple(params.grade),
        season=params.season,
        min_price_per_piece_pkr=params.min_price_per_piece_pkr,
        max_price_per_piece_pkr=params.max_price_per_piece_pkr,
        min_lot_price_pkr=params.min_lot_price_pkr,
        max_lot_price_pkr=params.max_lot_price_pkr,
        min_discount_percent=params.min_discount_percent,
        min_pieces=params.min_pieces,
        max_pieces=params.max_pieces,
        sort=params.sort,
    )


def _viewer(db: Session, principal: Principal, city: str | None) -> Viewer:
    verified, resolved_city = _buyer_view(db, principal, city)
    return Viewer(role=principal.role, verified=verified, city=resolved_city)


def _user(db: Session, principal: Principal) -> User:
    user = db.get(User, principal.user_id)
    if user is None:
        raise NotFound("That account no longer exists.")
    return user


def _items(db: Session, principal: Principal, result: SearchResult) -> list[SearchItemOut]:
    approval_service.preload_brands(db, result.lots)
    return [_item(db, principal, lot, result) for lot in result.lots]


def _item(db: Session, principal: Principal, lot: Lot, result: SearchResult) -> SearchItemOut:
    base = _browse_item(db, principal, lot)
    return SearchItemOut(**base.model_dump(), similarity=result.similarity.get(lot.id))


def _saved_out(db: Session, principal: Principal, row: SavedSearch) -> SavedSearchOut:
    params = SearchParams.model_validate(row.filters)
    new_matches = search_service.count_new_matches(
        db,
        saved=row,
        filters=_filters(params),
        viewer=_viewer(db, principal, params.city),
    )
    return SavedSearchOut(
        id=row.id,
        name=row.name,
        filters=params,
        last_run_at=row.last_run_at,
        new_matches=new_matches,
    )


@router.get("/categories", response_model=list[CategoryOut], operation_id="catalog_categories")
def categories(principal: CurrentPrincipal, db: Db) -> list[CategoryOut]:
    rows = db.scalars(select(Category).order_by(Category.sort_order, Category.name)).all()
    return [CategoryOut.model_validate(row) for row in rows]


class RecommendationOut(BrowseItemOut):
    score: float
    reasons: list[str]
    reason_codes: list[dict[str, str]] = Field(default_factory=list)


@router.get(
    "/recommendations",
    response_model=list[RecommendationOut],
    operation_id="catalog_recommendations",
)
def recommendations(
    principal: CurrentPrincipal,
    db: Db,
    limit: Annotated[int, Query(ge=1, le=24)] = 8,
) -> list[RecommendationOut]:
    """Lots this buyer is likely to want, each with the reasons it was chosen.

    Ranked from the buyer's own orders, saved searches and city. Only lots the
    buyer may open are considered.
    """
    viewer = _viewer(db, principal, None)
    ranked = recommendation_service.recommend(
        db, user_id=principal.user_id, viewer=viewer, limit=limit
    )
    approval_service.preload_brands(db, [rec.lot for rec in ranked])
    return [
        RecommendationOut(
            **_browse_item(db, principal, rec.lot).model_dump(),
            score=rec.score,
            reasons=rec.reasons,
            reason_codes=rec.reason_codes,
        )
        for rec in ranked
    ]


class MixedLotIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    budget_pkr: int = Field(ge=1_000, le=50_000_000)
    target_pieces: int = Field(ge=1, le=10_000)
    category_ids: list[str] = Field(default_factory=list, max_length=10)
    max_brands: int = Field(default=4, ge=2, le=6)
    city: str | None = Field(default=None, max_length=80)


class MixedLineOut(BaseModel):
    size: str
    color: str
    pieces: int


class MixedComponentOut(BaseModel):
    item: BrowseItemOut
    pieces: int
    lines: list[MixedLineOut]
    subtotal_pkr: int
    shipping_pkr: int
    total_pkr: int
    reason: str


class MixedLotOut(BaseModel):
    components: list[MixedComponentOut]
    pieces: int
    total_pkr: int
    brand_count: int
    budget_pkr: int
    target_pieces: int
    notes: list[str]
    added_to_cart: bool = False


def _build_mixed(db: Session, principal: Principal, body: MixedLotIn) -> tuple[User, Any]:
    user = _user(db, principal)
    _, city = _buyer_view(db, principal, body.city)
    proposal = mixed_lot_service.build(
        db,
        user=user,
        budget_pkr=body.budget_pkr,
        target_pieces=body.target_pieces,
        city=city or "",
        category_ids=tuple(body.category_ids),
        max_brands=body.max_brands,
    )
    return user, proposal


def _mixed_out(db: Session, principal: Principal, proposal: Any, added: bool) -> MixedLotOut:
    approval_service.preload_brands(db, [c.lot for c in proposal.components])
    return MixedLotOut(
        components=[
            MixedComponentOut(
                item=_browse_item(db, principal, c.lot),
                pieces=c.pieces,
                lines=[MixedLineOut(size=x.size, color=x.color, pieces=x.pieces) for x in c.lines],
                subtotal_pkr=c.subtotal_pkr,
                shipping_pkr=c.shipping_pkr,
                total_pkr=c.total_pkr,
                reason=c.reason,
            )
            for c in proposal.components
        ],
        pieces=proposal.pieces,
        total_pkr=proposal.total_pkr,
        brand_count=proposal.brand_count,
        budget_pkr=proposal.budget_pkr,
        target_pieces=proposal.target_pieces,
        notes=proposal.notes,
        added_to_cart=added,
    )


@router.post(
    "/mixed-lots",
    response_model=MixedLotOut,
    operation_id="catalog_build_mixed_lot",
)
def build_mixed_lot(body: MixedLotIn, principal: CurrentPrincipal, db: Db) -> MixedLotOut:
    """Propose slow stock from several brands that fits a budget and piece count.

    Each part is an ordinary part lot purchase from its own brand, priced by
    the same rules as checkout. Nothing is reserved until checkout.
    """
    _, proposal = _build_mixed(db, principal, body)
    return _mixed_out(db, principal, proposal, added=False)


@router.post(
    "/mixed-lots/cart",
    response_model=MixedLotOut,
    operation_id="catalog_mixed_lot_to_cart",
)
def mixed_lot_to_cart(body: MixedLotIn, principal: CurrentPrincipal, db: Db) -> MixedLotOut:
    """Build the proposal again from current stock and put every part in the cart."""
    user, proposal = _build_mixed(db, principal, body)
    mixed_lot_service.add_to_cart(db, user=user, proposal=proposal)
    db.commit()
    return _mixed_out(db, principal, proposal, added=True)


@router.get("/search", response_model=SearchOut, operation_id="catalog_search")
def search_catalog(
    principal: CurrentPrincipal,
    db: Db,
    params: Annotated[SearchQuery, Query()],
) -> SearchOut:
    """Filter, sort and search the listings this viewer may see."""
    result = search_service.search(
        db,
        filters=_filters(params),
        viewer=_viewer(db, principal, params.city),
        limit=params.limit,
        offset=params.offset,
    )
    return SearchOut(
        items=_items(db, principal, result),
        total=result.total,
        limit=params.limit,
        offset=params.offset,
        method=result.method,
        note=result.note,
    )


@router.post("/search/photo", response_model=SearchOut, operation_id="catalog_search_photo")
async def search_catalog_by_photo(
    principal: CurrentPrincipal,
    db: Db,
    file: Annotated[UploadFile, File()],
    city: Annotated[str | None, Query(max_length=80)] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 24,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> SearchOut:
    """Find listings that look like a photograph. The image is not stored."""
    from ...storage import ALLOWED_IMAGE_TYPES, StorageError, validate_upload

    data = await file.read()
    try:
        validate_upload(data, file.content_type or "", allowed=ALLOWED_IMAGE_TYPES)
    except StorageError as exc:
        from ...core.errors import ValidationFailed

        raise ValidationFailed(str(exc)) from exc

    result = search_service.search_by_photo(
        db,
        data=data,
        filters=SearchFilters(),
        viewer=_viewer(db, principal, city),
        limit=limit,
        offset=offset,
    )
    return SearchOut(
        items=_items(db, principal, result),
        total=result.total,
        limit=limit,
        offset=offset,
        method=result.method,
        note=result.note,
    )


@router.get(
    "/saved-searches",
    response_model=list[SavedSearchOut],
    operation_id="catalog_saved_searches",
)
def list_saved_searches(principal: CurrentPrincipal, db: Db) -> list[SavedSearchOut]:
    rows = search_service.list_saved(db, user=_user(db, principal))
    return [_saved_out(db, principal, row) for row in rows]


@router.post(
    "/saved-searches",
    response_model=SavedSearchOut,
    status_code=status.HTTP_201_CREATED,
    operation_id="catalog_save_search",
)
def save_search(body: SavedSearchIn, principal: CurrentPrincipal, db: Db) -> SavedSearchOut:
    row = search_service.save(
        db,
        user=_user(db, principal),
        name=body.name,
        filters=body.filters.model_dump(mode="json", exclude_defaults=True),
    )
    db.commit()
    return _saved_out(db, principal, row)


@router.get(
    "/saved-searches/{saved_id}/results",
    response_model=SavedSearchRunOut,
    operation_id="catalog_run_saved_search",
)
def run_saved_search(
    saved_id: str,
    principal: CurrentPrincipal,
    db: Db,
    limit: Annotated[int, Query(ge=1, le=100)] = 24,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> SavedSearchRunOut:
    """Run a saved search and mark its current matches as seen."""
    row = search_service.get_saved(db, user=_user(db, principal), saved_id=saved_id)
    params = SearchParams.model_validate(row.filters)
    filters = _filters(params)
    viewer = _viewer(db, principal, params.city)
    new_matches = search_service.count_new_matches(db, saved=row, filters=filters, viewer=viewer)
    result = search_service.search(db, filters=filters, viewer=viewer, limit=limit, offset=offset)
    items = _items(db, principal, result)
    row.last_run_at = utcnow()
    db.commit()
    return SavedSearchRunOut(
        items=items,
        total=result.total,
        limit=limit,
        offset=offset,
        method=result.method,
        note=result.note,
        new_matches=new_matches,
    )


@router.delete(
    "/saved-searches/{saved_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    operation_id="catalog_remove_saved_search",
)
def delete_saved_search(saved_id: str, principal: CurrentPrincipal, db: Db) -> None:
    row = search_service.get_saved(db, user=_user(db, principal), saved_id=saved_id)
    db.delete(row)
    db.commit()
