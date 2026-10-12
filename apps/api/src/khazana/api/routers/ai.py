"""AI endpoints.

Step four of each Phase 2 capability: expose it. Conventions applied here so
the generated OpenAPI document is usable by a client generator:

- An explicit ``operation_id`` on every route, in ``resource_action`` form, so
  generated method names read as ``ai.listing_draft()`` rather than something
  derived from the URL.
- One tag, ``ai``, with lowercase naming.
- Specific summaries and descriptions. "Draft a listing from photographs"
  rather than "Post listing".
- Every response has a declared model, and the error shapes are documented
  rather than implied.

Two rules hold across all of them. Every route states its cost, because an AI
call that silently spends money is how a bill becomes a surprise. And every
route that produces a draft returns it as a draft, never applying it.
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, File, Form, Query, UploadFile, status
from pydantic import BaseModel, Field

from ...ai import embeddings
from ...ai.features import (
    assistant,
    listing_from_photos,
    manifest_extract,
    pricing,
    risk_scoring,
)
from ...ai.schemas import (
    AssistantAnswer,
    ListingDraft,
    ManifestLineDraft,
    PriceSuggestion,
    RiskScore,
)
from ...core.errors import AppError
from ...core.tenancy import assert_owns
from ...models import Lot
from ...models.enums import ConditionGrade, PhotoKind
from ...storage import ALLOWED_IMAGE_TYPES, StorageError, validate_upload
from ..deps import CurrentBrand, CurrentPrincipal, Db

router = APIRouter(prefix="/ai", tags=["ai"])

MAX_PHOTOS = 8


class CostOut(BaseModel):
    """What one request spent.

    Returned on every AI response on purpose. A feature whose cost is visible
    at the point of use is a feature nobody is surprised by at the end of the
    month.
    """

    usd: str = Field(description="Cost of this request in US dollars")
    model: str
    from_fixture: bool = Field(
        description="True when the reply came from a recorded fixture rather than the API"
    )


class ListingDraftOut(BaseModel):
    draft: ListingDraft
    needs_review: bool = Field(description="True when a person should check before submitting")
    review_reasons: list[str]
    photos_sent: int
    bytes_saved: int = Field(description="Bytes saved by compressing before the call")
    cost: CostOut


class ManifestExtractOut(BaseModel):
    lines: list[ManifestLineDraft]
    declared_total: int | None
    line_total: int
    balanced: bool = Field(description="Whether the lines sum to the total the file states")
    difference: int | None
    needs_review: bool
    corrections: list[str]
    notes: list[str]
    summary: str
    cost: CostOut


class PriceSuggestionOut(BaseModel):
    suggestion: PriceSuggestion
    comparables_used: int
    clamped: bool = Field(description="True when the suggestion was held inside the brand band")
    clamp_note: str | None
    lot_price_range_pkr: list[int]
    cost: CostOut


class SearchHitOut(BaseModel):
    lot_code: str
    title: str
    similarity: float
    price_per_piece_pkr: int
    stock_city: str


class SearchOut(BaseModel):
    hits: list[SearchHitOut]
    method: str = Field(description="vector or keyword, depending on database support")


class AssistantOut(BaseModel):
    answer: AssistantAnswer
    tools_used: list[str]
    grounded: bool = Field(
        description="False when the reply made a claim with no lookup behind it"
    )
    cost: CostOut


class RiskScoreOut(BaseModel):
    score: RiskScore
    model_score: int
    computed_score: int
    needs_human_review: bool
    cost: CostOut


class AssistantIn(BaseModel):
    message: str = Field(min_length=1, max_length=2_000)
    city: str = Field(default="", max_length=80)


def _cost(result: Any) -> CostOut:
    return CostOut(
        usd=str(result.cost_usd), model=result.model, from_fixture=result.from_fixture
    )


@router.post(
    "/listings/draft",
    operation_id="ai_listing_draft",
    summary="Draft a listing from photographs",
    response_model=ListingDraftOut,
    responses={
        402: {"description": "An AI spend cap was reached before the call was made"},
        422: {"description": "No photographs, an unreadable image, or no category taxonomy"},
        503: {"description": "The feature is switched off by its kill switch"},
    },
)
async def draft_listing(
    principal: CurrentBrand,
    db: Db,
    brand_id: Annotated[str, Form(description="The brand the lot belongs to")],
    files: Annotated[list[UploadFile], File(description="Lot photographs, JPEG or PNG")],
    title: Annotated[str, Form()] = "",
    notes: Annotated[str, Form()] = "",
    season: Annotated[str, Form()] = "",
    claimed_grade: Annotated[ConditionGrade | None, Form()] = None,
) -> ListingDraftOut:
    """Produce a draft listing from photographs of one lot.

    The result is always a draft. Title, description and category come back
    for the brand to correct, and the piece count, price and manifest are
    never touched by a model.
    """
    assert_owns(principal, brand_id)

    if len(files) > MAX_PHOTOS:
        raise AppError(f"Upload at most {MAX_PHOTOS} photographs.").as_http()

    photos: list[tuple[PhotoKind, bytes]] = []
    for index, upload in enumerate(files):
        data = await upload.read()
        try:
            validate_upload(data, upload.content_type or "", allowed=ALLOWED_IMAGE_TYPES)
        except StorageError as exc:
            raise AppError(str(exc)).as_http() from exc
        # Position is the only hint available about which view each shot is,
        # until the brand labels them in the catalogue UI in Phase 3.
        kind = PhotoKind.FRONT if index == 0 else PhotoKind.FULL_LOT
        photos.append((kind, data))

    try:
        outcome = listing_from_photos.draft_from_photos(
            db,
            photos=photos,
            brand_id=brand_id,
            user_id=principal.user_id,
            brand_title=title,
            brand_notes=notes,
            season=season,
            claimed_grade=claimed_grade,
        )
    except AppError as exc:
        raise exc.as_http() from exc

    return ListingDraftOut(
        draft=outcome.draft,
        needs_review=outcome.needs_review,
        review_reasons=outcome.review_reasons,
        photos_sent=outcome.image_stats.get("photos_sent", 0),
        bytes_saved=outcome.image_stats.get("bytes_saved", 0),
        cost=_cost(outcome.result),
    )


@router.post(
    "/manifests/extract",
    operation_id="ai_manifest_extract",
    summary="Extract a manifest from a spreadsheet",
    response_model=ManifestExtractOut,
    responses={
        402: {"description": "An AI spend cap was reached before the call was made"},
        422: {"description": "Not a CSV, empty, too many rows, or an unreadable encoding"},
    },
)
async def extract_manifest(
    principal: CurrentBrand,
    db: Db,
    brand_id: Annotated[str, Form()],
    file: Annotated[UploadFile, File(description="CSV exported from the brand spreadsheet")],
    lot_id: Annotated[str | None, Form()] = None,
) -> ManifestExtractOut:
    """Turn a brand spreadsheet into manifest lines.

    Nothing is reconciled silently. When the rows do not sum to the total the
    file states, the difference is reported and the lines come back exactly as
    read, for a person to accept or reject.
    """
    assert_owns(principal, brand_id)

    data = await file.read()
    try:
        outcome = manifest_extract.extract(
            db,
            data=data,
            filename=file.filename or "upload.csv",
            brand_id=brand_id,
            user_id=principal.user_id,
            lot_id=lot_id,
        )
    except AppError as exc:
        raise exc.as_http() from exc

    return ManifestExtractOut(
        lines=outcome.lines,
        declared_total=outcome.declared_total,
        line_total=outcome.line_total,
        balanced=outcome.balanced,
        difference=outcome.difference,
        needs_review=outcome.needs_review,
        corrections=outcome.corrections,
        notes=outcome.notes,
        summary=outcome.summary(),
        cost=_cost(outcome.result),
    )


@router.post(
    "/lots/{lot_id}/price-suggestion",
    operation_id="ai_price_suggest",
    summary="Suggest a discount band for a lot",
    response_model=PriceSuggestionOut,
    responses={
        402: {"description": "An AI spend cap was reached before the call was made"},
        404: {"description": "No such lot, or it belongs to another brand"},
    },
)
def suggest_price(lot_id: str, principal: CurrentBrand, db: Db) -> PriceSuggestionOut:
    """Suggest a discount band, with the reasoning and the evidence behind it.

    Always a band, never a single number, and always held inside the brand's
    own policy band. When there are too few comparable sales the suggestion is
    marked as rules based so the interface can label it honestly.
    """
    lot = db.get(Lot, lot_id)
    if lot is None:
        from ...core.errors import NotFound

        raise NotFound("That lot does not exist.").as_http()
    assert_owns(principal, lot.brand_id)

    try:
        outcome = pricing.suggest(db, lot_id, user_id=principal.user_id)
    except AppError as exc:
        raise exc.as_http() from exc

    retail_total = lot.retail_price_per_piece_pkr * lot.total_pieces
    low, high = outcome.price_range_pkr(retail_total)

    return PriceSuggestionOut(
        suggestion=outcome.suggestion,
        comparables_used=outcome.comparables_used,
        clamped=outcome.clamped,
        clamp_note=outcome.clamp_note,
        lot_price_range_pkr=[low, high],
        cost=_cost(outcome.result),
    )


@router.get(
    "/search",
    operation_id="ai_search_lots",
    summary="Search lots by meaning rather than keywords",
    response_model=SearchOut,
    responses={503: {"description": "Vector search needs PostgreSQL with pgvector"}},
)
def semantic_search(
    principal: CurrentPrincipal,
    db: Db,
    q: Annotated[str, Query(min_length=2, max_length=200, description="What the buyer wants")],
    limit: Annotated[int, Query(ge=1, le=50)] = 20,
) -> SearchOut:
    """Find lots by meaning.

    Only live, approved, non private lots are searchable, and that filter is
    inside the query rather than applied afterwards.
    """
    try:
        hits = embeddings.search_by_text(db, q, limit=limit)
        method = "vector"
    except embeddings.EmbeddingError as exc:
        # On SQLite there is no vector search. Saying so beats returning an
        # empty list, which is indistinguishable from a genuine miss.
        raise AppError(str(exc)).as_http() from exc

    return SearchOut(
        hits=[
            SearchHitOut(
                lot_code=hit.lot.lot_code,
                title=hit.lot.title,
                similarity=round(hit.similarity, 3),
                price_per_piece_pkr=round(hit.lot.price_per_piece_pkr),
                stock_city=hit.lot.stock_city,
            )
            for hit in hits
        ],
        method=method,
    )


@router.post(
    "/assistant/ask",
    operation_id="ai_assistant_ask",
    summary="Ask the buyer assistant a question",
    response_model=AssistantOut,
    responses={
        402: {"description": "An AI spend cap was reached before the call was made"},
        422: {"description": "The message was empty"},
    },
)
def ask_assistant(payload: AssistantIn, principal: CurrentPrincipal, db: Db) -> AssistantOut:
    """Answer one buyer question in English, Urdu or Roman Urdu.

    The reply is grounded: every factual claim comes from a database lookup
    made during this request. When no lookup could answer the question, the
    assistant says so rather than guessing, and ``grounded`` reports it.
    """
    try:
        turn = assistant.ask(
            db,
            message=payload.message,
            buyer_user_id=principal.user_id,
            buyer_city=payload.city,
        )
    except AppError as exc:
        raise exc.as_http() from exc

    return AssistantOut(
        answer=turn.answer,
        tools_used=turn.answer.tool_calls_made,
        grounded=turn.is_grounded,
        cost=CostOut(
            usd=str(turn.total_cost_usd),
            model=turn.answer_result.model,
            from_fixture=turn.answer_result.from_fixture,
        ),
    )


@router.post(
    "/lots/{lot_id}/risk-score",
    operation_id="ai_risk_score",
    summary="Score a listing for review priority",
    status_code=status.HTTP_200_OK,
    response_model=RiskScoreOut,
    responses={
        402: {"description": "An AI spend cap was reached before the call was made"},
        404: {"description": "No such lot, or it belongs to another brand"},
    },
)
def score_listing(lot_id: str, principal: CurrentPrincipal, db: Db) -> RiskScoreOut:
    """Score one listing for how much human attention it needs.

    Orders the review queue. It never approves or rejects anything, and the
    structural checks are computed rather than judged, so a reassuring model
    cannot talk a broken listing down the queue.
    """
    lot = db.get(Lot, lot_id)
    if lot is None:
        from ...core.errors import NotFound

        raise NotFound("That lot does not exist.").as_http()
    assert_owns(principal, lot.brand_id)

    try:
        outcome = risk_scoring.score_lot(db, lot_id, user_id=principal.user_id)
    except AppError as exc:
        raise exc.as_http() from exc

    return RiskScoreOut(
        score=outcome.score,
        model_score=outcome.model_score,
        computed_score=outcome.computed_score,
        needs_human_review=outcome.needs_human_review,
        cost=_cost(outcome.result),
    )
