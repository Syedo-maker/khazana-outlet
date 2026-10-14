"""Catalog endpoints: lots, manifests, photographs, approvals and browsing.

Who may call what, stated once because it is the security model of this
router:

- Everything under `/lots` is for the owning brand, enforced by `assert_owns`
  on every path that names a lot. It answers 404 rather than 403, so probing
  identifiers tells an attacker nothing about what exists.
- `/catalog` is the buyer facing path and is the only one that does not check
  ownership. It applies `approval_service.visibility_filter` instead, which is
  the single definition of what a buyer may see.
- Admins pass every ownership check, by design, and still see the same
  visibility rules on the browse path.

Route order matters here. `/lots/queue` is declared before `/lots/{lot_id}`
because FastAPI matches in declaration order and would otherwise read "queue"
as a lot identifier.
"""

from __future__ import annotations

from datetime import date
from typing import Annotated, Any, cast

from fastapi import APIRouter, File, Form, Query, Request, UploadFile, status
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy.orm import Session

from ...core.errors import NotFound, ValidationFailed
from ...core.tenancy import assert_owns
from ...models import Lot, User
from ...models.enums import (
    ConditionGrade,
    LotStatus,
    PhotoKind,
    VerificationStatus,
    Visibility,
)
from ...services import approval_service, catalog_service
from ..deps import CurrentBrand, CurrentPrincipal, Db, Principal, client_ip

router = APIRouter(tags=["catalog"])


# ------------------------------------------------------------------ schemas


class LotCreateIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    brand_id: str
    title: str = Field(min_length=3, max_length=200)
    category_id: str
    condition_grade: ConditionGrade
    total_pieces: int = Field(gt=0, le=1_000_000)
    retail_price_per_piece_pkr: int = Field(gt=0)
    lot_price_pkr: int = Field(gt=0)
    min_order_pieces: int = Field(gt=0)
    stock_city: str = Field(min_length=2, max_length=80)
    description: str | None = None
    season: str | None = Field(default=None, max_length=40)
    weight_kg: float | None = Field(default=None, ge=0)
    cartons: int | None = Field(default=None, ge=0)
    expiry_date: date | None = None
    available_until: date | None = None


class LotUpdateIn(BaseModel):
    """Every field optional. Only what is sent is changed.

    `status` and `visibility` are absent on purpose: each has its own endpoint
    with its own rules, and accepting them here would route around the state
    machine and the brand protection checks.
    """

    model_config = ConfigDict(extra="forbid")

    title: str | None = Field(default=None, min_length=3, max_length=200)
    category_id: str | None = None
    condition_grade: ConditionGrade | None = None
    total_pieces: int | None = Field(default=None, gt=0, le=1_000_000)
    retail_price_per_piece_pkr: int | None = Field(default=None, gt=0)
    lot_price_pkr: int | None = Field(default=None, gt=0)
    min_order_pieces: int | None = Field(default=None, gt=0)
    stock_city: str | None = Field(default=None, min_length=2, max_length=80)
    description: str | None = None
    season: str | None = Field(default=None, max_length=40)
    weight_kg: float | None = Field(default=None, ge=0)
    cartons: int | None = Field(default=None, ge=0)
    expiry_date: date | None = None
    available_until: date | None = None


class ManifestLineIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    size: str = Field(min_length=1, max_length=32)
    color: str = Field(min_length=1, max_length=48)
    pieces: int = Field(gt=0)


class ManifestIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    lines: list[ManifestLineIn] = Field(min_length=1)


class DefectIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    issue: str = Field(min_length=3, max_length=255)
    pieces_affected: int = Field(gt=0)
    photo_id: str | None = None


class DefectsIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    defects: list[DefectIn] = Field(default_factory=list)


class PhotoOrderIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    photo_ids: list[str] = Field(min_length=1)


class VisibilityIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    visibility: Visibility


class RegionLockIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    cities: list[str] = Field(default_factory=list)


class NoteIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    note: str | None = Field(default=None, max_length=500)


class RejectIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    note: str = Field(min_length=approval_service.MIN_REJECTION_NOTE, max_length=500)


class ApproveIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    note: str | None = Field(default=None, max_length=500)
    visibility: Visibility | None = None
    publish: bool = True


class ManifestLineOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    size: str
    color: str
    pieces: int


class PhotoOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    file_key: str
    kind: PhotoKind
    sort_order: int
    width: int | None = None
    height: int | None = None
    bytes_stored: int | None = None


class DefectOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    issue: str
    pieces_affected: int
    photo_id: str | None = None


class LotOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    lot_code: str
    brand_id: str
    category_id: str
    title: str
    description: str | None = None
    season: str | None = None
    condition_grade: ConditionGrade
    total_pieces: int
    retail_price_per_piece_pkr: int
    lot_price_pkr: int
    min_order_pieces: int
    stock_city: str
    status: LotStatus
    visibility: Visibility
    expiry_date: date | None = None
    available_until: date | None = None
    # Derived in the model, so the client never recomputes them and cannot
    # disagree with the server about a discount.
    price_per_piece_pkr: float
    discount_percent: float
    manifest_total: int
    is_manifest_balanced: bool


class LotDetailOut(LotOut):
    manifest_lines: list[ManifestLineOut] = Field(default_factory=list)
    photos: list[PhotoOut] = Field(default_factory=list)
    defects: list[DefectOut] = Field(default_factory=list)
    # The effective region lock: this lot's own cities, or the brand default
    # when the lot has none. `_detail` computes which, and the validator below
    # handles the ORM rows pydantic reads off the relationship first.
    excluded_cities: list[str] = Field(default_factory=list)

    @field_validator("excluded_cities", mode="before")
    @classmethod
    def _city_names(cls, value: object) -> object:
        """Accept either city strings or the LotExcludedCity rows.

        `model_validate` populates this from the relationship, which yields
        ORM objects and fails a list[str] field. Reducing them to their city
        here means the field works both from the ORM and when `_detail`
        assigns the computed list.
        """
        if isinstance(value, list):
            return [getattr(item, "city", item) for item in value]
        return value


class LotListOut(BaseModel):
    items: list[LotOut]
    total: int
    limit: int
    offset: int


class ReadinessOut(BaseModel):
    ready: bool
    blockers: list[str]
    warnings: list[str]


class ManifestImportOut(BaseModel):
    """A proposal. Nothing has been saved.

    The brand reviews these rows and then calls PUT /manifest to commit them,
    because an AI reading of a spreadsheet is a suggestion and the manifest is
    a commitment to a buyer.
    """

    rows: list[ManifestLineIn]
    total_pieces: int
    declared_total: int | None = None
    lot_total_pieces: int
    matches_lot_total: bool
    confidence: float
    warnings: list[str]
    model: str
    from_fixture: bool
    cost_usd: float


class QueueItemOut(BaseModel):
    lot: LotOut
    risk_score: int
    risk_band: str
    findings: list[str]


class ApprovalOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    action: str
    actor_user_id: str | None = None
    actor_role: str
    visibility_at_action: Visibility
    note: str | None = None
    created_at: Any


class BrowseItemOut(BaseModel):
    """A listing as one viewer may see it.

    `brand_name` is whatever that viewer is allowed to know: the real name, or
    the unbranded label. The real name is never in this payload for an
    unbranded lot, because filtering it in the client would mean shipping it
    to the client first.
    """

    lot: LotOut
    brand_name: str
    brand_is_hidden: bool


class BrowseOut(BaseModel):
    items: list[BrowseItemOut]
    total: int
    limit: int
    offset: int


# ------------------------------------------------------------------ internals


def _actor(db: Session, principal: Principal) -> User:
    user = db.get(User, principal.user_id)
    if user is None:
        raise NotFound("That account no longer exists.")
    return user


def _owned(db: Session, principal: Principal, lot_id: str) -> Lot:
    """Load a lot the caller owns, or answer 404.

    Every lot path goes through this. `assert_owns` raises `CrossTenant`,
    which is reported as 404, so a brand probing another brand's identifiers
    cannot tell a wrong guess from a lot it is not allowed to see.
    """
    lot = catalog_service.get_lot(db, lot_id)
    assert_owns(principal, lot.brand_id)
    return lot


def _detail(db: Session, lot: Lot) -> LotDetailOut:
    payload = LotDetailOut.model_validate(lot)
    payload.excluded_cities = approval_service.excluded_cities_for(db, lot)
    return payload


# ---------------------------------------------------------------------- lots


@router.post(
    "/lots",
    response_model=LotDetailOut,
    status_code=status.HTTP_201_CREATED,
    operation_id="lots_create",
)
def create_lot(
    body: LotCreateIn,
    principal: CurrentBrand,
    db: Db,
    request: Request,
) -> LotDetailOut:
    """Create a draft lot.

    Starts in draft at the brand's default protection level. Nothing reaches a
    buyer until it has been through approval.
    """
    assert_owns(principal, body.brand_id)
    data = body.model_dump(exclude_none=True)
    data.pop("brand_id")

    lot = catalog_service.create_lot(
        db,
        brand_id=body.brand_id,
        actor=_actor(db, principal),
        data=data,
        ip=client_ip(request),
    )
    db.commit()
    return _detail(db, catalog_service.get_lot(db, lot.id))


@router.get(
    "/lots",
    response_model=LotListOut,
    operation_id="lots_list",
)
def list_lots(
    principal: CurrentBrand,
    db: Db,
    lot_status: Annotated[LotStatus | None, Query(alias="status")] = None,
    search: Annotated[str | None, Query(max_length=120)] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> LotListOut:
    """The caller's own lots, newest first. An admin sees every brand's."""
    brand_ids = None if principal.is_admin else principal.brand_ids
    rows, total = catalog_service.list_lots(
        db, brand_ids=brand_ids, status=lot_status, search=search, limit=limit, offset=offset
    )
    return LotListOut(
        items=[LotOut.model_validate(lot) for lot in rows],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get(
    "/lots/queue",
    response_model=list[QueueItemOut],
    operation_id="lots_approval_queue",
)
def approval_queue(
    principal: CurrentBrand,
    db: Db,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> list[QueueItemOut]:
    """Lots awaiting approval, riskiest first.

    The risk score orders the queue and decides nothing. See
    `docs/ai-architecture.md` section 2.

    Declared before `/lots/{lot_id}` so that "queue" is not read as an
    identifier.
    """
    brand_ids = None if principal.is_admin else principal.brand_ids
    items = approval_service.pending_queue(db, brand_ids=brand_ids, limit=limit)
    return [
        QueueItemOut(
            lot=LotOut.model_validate(item.lot),
            risk_score=item.risk_score,
            risk_band=item.risk_band,
            findings=item.findings,
        )
        for item in items
    ]


@router.get(
    "/lots/{lot_id}",
    response_model=LotDetailOut,
    operation_id="lots_detail",
)
def get_lot(lot_id: str, principal: CurrentPrincipal, db: Db) -> LotDetailOut:
    return _detail(db, _owned(db, principal, lot_id))


@router.patch(
    "/lots/{lot_id}",
    response_model=LotDetailOut,
    operation_id="lots_update",
)
def update_lot(
    lot_id: str,
    body: LotUpdateIn,
    principal: CurrentBrand,
    db: Db,
    request: Request,
) -> LotDetailOut:
    """Edit a lot.

    A material change to an approved lot resets it to draft, because the brand
    approved a specific payload. The response status tells the caller that
    happened.
    """
    lot = _owned(db, principal, lot_id)
    changes = body.model_dump(exclude_unset=True)
    if not changes:
        raise ValidationFailed("Send at least one field to change.")

    catalog_service.update_lot(
        db, lot=lot, actor=_actor(db, principal), changes=changes, ip=client_ip(request)
    )
    db.commit()
    return _detail(db, catalog_service.get_lot(db, lot_id))


@router.get(
    "/lots/{lot_id}/readiness",
    response_model=ReadinessOut,
    operation_id="lots_readiness",
)
def lot_readiness(lot_id: str, principal: CurrentBrand, db: Db) -> ReadinessOut:
    """What still stands between this lot and a buyer seeing it.

    A checklist rather than one error at a time, so the editor can show
    progress while the brand works through it.
    """
    lot = _owned(db, principal, lot_id)
    state = catalog_service.readiness(db, lot)
    return ReadinessOut(ready=state.ready, blockers=state.blockers, warnings=state.warnings)


# ------------------------------------------------------------------ manifest


@router.put(
    "/lots/{lot_id}/manifest",
    response_model=LotDetailOut,
    operation_id="lots_set_manifest",
)
def set_manifest(
    lot_id: str,
    body: ManifestIn,
    principal: CurrentBrand,
    db: Db,
    request: Request,
) -> LotDetailOut:
    """Replace the manifest.

    The whole table is sent, not a patch. A per row API would let a half
    applied edit leave the sum wrong between requests, and the sum matching
    the lot total is the rule buyers judge a manifest on.
    """
    lot = _owned(db, principal, lot_id)
    catalog_service.set_manifest(
        db,
        lot=lot,
        actor=_actor(db, principal),
        lines=[line.model_dump() for line in body.lines],
        ip=client_ip(request),
    )
    db.commit()
    return _detail(db, catalog_service.get_lot(db, lot_id))


@router.post(
    "/lots/{lot_id}/manifest/import",
    response_model=ManifestImportOut,
    operation_id="lots_import_manifest",
)
async def import_manifest(
    lot_id: str,
    principal: CurrentBrand,
    db: Db,
    request: Request,
    file: Annotated[UploadFile, File()],
) -> ManifestImportOut:
    """Read a brand spreadsheet into manifest rows, without saving them.

    Returns a proposal. The brand reviews it and commits it with
    PUT /manifest. Two endpoints rather than one because the extraction is an
    AI suggestion and the manifest is a commitment to a buyer, and collapsing
    them would make the model's reading of a spreadsheet binding.
    """
    lot = _owned(db, principal, lot_id)
    data = await file.read()

    outcome = catalog_service.import_manifest(
        db,
        lot=lot,
        actor=_actor(db, principal),
        data=data,
        filename=file.filename or "manifest.csv",
        ip=client_ip(request),
    )
    # The import itself writes nothing to the lot, but the gateway recorded a
    # job and its cost, and the audit entry belongs with it.
    db.commit()

    return ManifestImportOut(
        rows=[
            ManifestLineIn(
                size=str(row["size"]),
                color=str(row["color"]),
                # The extractor returns plain dictionaries whose values are
                # typed as object. Pydantic validates the piece count on the
                # way into the model regardless of what the cast claims.
                pieces=cast(int, row["pieces"]),
            )
            for row in outcome.rows
        ],
        total_pieces=outcome.total_pieces,
        declared_total=outcome.declared_total,
        lot_total_pieces=lot.total_pieces,
        matches_lot_total=outcome.total_pieces == lot.total_pieces,
        confidence=outcome.confidence,
        warnings=outcome.warnings,
        model=outcome.model,
        from_fixture=outcome.from_fixture,
        cost_usd=outcome.cost_usd,
    )


@router.put(
    "/lots/{lot_id}/defects",
    response_model=LotDetailOut,
    operation_id="lots_set_defects",
)
def set_defects(
    lot_id: str,
    body: DefectsIn,
    principal: CurrentBrand,
    db: Db,
    request: Request,
) -> LotDetailOut:
    """Replace the itemised defect list. Required for grade C."""
    lot = _owned(db, principal, lot_id)
    catalog_service.set_defects(
        db,
        lot=lot,
        actor=_actor(db, principal),
        defects=[defect.model_dump() for defect in body.defects],
        ip=client_ip(request),
    )
    db.commit()
    return _detail(db, catalog_service.get_lot(db, lot_id))


# -------------------------------------------------------------------- photos


@router.post(
    "/lots/{lot_id}/photos",
    response_model=PhotoOut,
    status_code=status.HTTP_201_CREATED,
    operation_id="lots_add_photo",
)
async def add_photo(
    lot_id: str,
    principal: CurrentBrand,
    db: Db,
    request: Request,
    file: Annotated[UploadFile, File()],
    kind: Annotated[PhotoKind, Form()],
) -> PhotoOut:
    """Upload one photograph.

    The file is validated on its own bytes rather than its declared type, then
    resized and recompressed. Only the processed version is stored.
    """
    lot = _owned(db, principal, lot_id)
    data = await file.read()

    photo = catalog_service.add_photo(
        db,
        lot=lot,
        actor=_actor(db, principal),
        data=data,
        content_type=file.content_type or "application/octet-stream",
        kind=kind,
        ip=client_ip(request),
    )
    db.commit()
    return PhotoOut.model_validate(photo)


@router.put(
    "/lots/{lot_id}/photos/order",
    response_model=list[PhotoOut],
    operation_id="lots_reorder_photos",
)
def reorder_photos(
    lot_id: str,
    body: PhotoOrderIn,
    principal: CurrentBrand,
    db: Db,
    request: Request,
) -> list[PhotoOut]:
    """Set the gallery order. The first photograph is the one buyers see."""
    lot = _owned(db, principal, lot_id)
    photos = catalog_service.reorder_photos(
        db,
        lot=lot,
        actor=_actor(db, principal),
        photo_ids=body.photo_ids,
        ip=client_ip(request),
    )
    db.commit()
    return [PhotoOut.model_validate(photo) for photo in photos]


@router.delete(
    "/lots/{lot_id}/photos/{photo_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    operation_id="lots_remove_photo",
)
def remove_photo(
    lot_id: str,
    photo_id: str,
    principal: CurrentBrand,
    db: Db,
    request: Request,
) -> None:
    lot = _owned(db, principal, lot_id)
    catalog_service.remove_photo(
        db, lot=lot, actor=_actor(db, principal), photo_id=photo_id, ip=client_ip(request)
    )
    db.commit()


# ----------------------------------------------------- approvals and protection


@router.post(
    "/lots/{lot_id}/submit",
    response_model=LotDetailOut,
    operation_id="lots_submit",
)
def submit_lot(lot_id: str, principal: CurrentBrand, db: Db, request: Request) -> LotDetailOut:
    """Submit a draft for approval. Refused if the readiness checks fail."""
    lot = _owned(db, principal, lot_id)
    approval_service.submit(db, lot=lot, actor=_actor(db, principal), ip=client_ip(request))
    db.commit()
    return _detail(db, catalog_service.get_lot(db, lot_id))


@router.post(
    "/lots/{lot_id}/approve",
    response_model=LotDetailOut,
    operation_id="lots_approve",
)
def approve_lot(
    lot_id: str,
    body: ApproveIn,
    principal: CurrentBrand,
    db: Db,
    request: Request,
) -> LotDetailOut:
    """Approve a submitted lot, and by default put it live.

    Writes an append only approval record holding the exact listing as
    approved, so a later edit cannot change what the brand agreed to.
    """
    lot = _owned(db, principal, lot_id)
    approval_service.approve(
        db,
        lot=lot,
        actor=_actor(db, principal),
        visibility=body.visibility,
        note=body.note,
        publish=body.publish,
        ip=client_ip(request),
    )
    db.commit()
    return _detail(db, catalog_service.get_lot(db, lot_id))


@router.post(
    "/lots/{lot_id}/reject",
    response_model=LotDetailOut,
    operation_id="lots_reject",
)
def reject_lot(
    lot_id: str,
    body: RejectIn,
    principal: CurrentBrand,
    db: Db,
    request: Request,
) -> LotDetailOut:
    """Send a submitted lot back to draft with a reason."""
    lot = _owned(db, principal, lot_id)
    approval_service.reject(
        db, lot=lot, actor=_actor(db, principal), note=body.note, ip=client_ip(request)
    )
    db.commit()
    return _detail(db, catalog_service.get_lot(db, lot_id))


@router.post(
    "/lots/{lot_id}/publish",
    response_model=LotDetailOut,
    operation_id="lots_publish",
)
def publish_lot(lot_id: str, principal: CurrentBrand, db: Db, request: Request) -> LotDetailOut:
    lot = _owned(db, principal, lot_id)
    approval_service.publish(db, lot=lot, actor=_actor(db, principal), ip=client_ip(request))
    db.commit()
    return _detail(db, catalog_service.get_lot(db, lot_id))


@router.post(
    "/lots/{lot_id}/pause",
    response_model=LotDetailOut,
    operation_id="lots_pause",
)
def pause_lot(
    lot_id: str, body: NoteIn, principal: CurrentBrand, db: Db, request: Request
) -> LotDetailOut:
    """Take a live lot out of the catalogue, keeping its approval."""
    lot = _owned(db, principal, lot_id)
    approval_service.pause(
        db, lot=lot, actor=_actor(db, principal), note=body.note, ip=client_ip(request)
    )
    db.commit()
    return _detail(db, catalog_service.get_lot(db, lot_id))


@router.post(
    "/lots/{lot_id}/resume",
    response_model=LotDetailOut,
    operation_id="lots_resume",
)
def resume_lot(lot_id: str, principal: CurrentBrand, db: Db, request: Request) -> LotDetailOut:
    lot = _owned(db, principal, lot_id)
    approval_service.resume(db, lot=lot, actor=_actor(db, principal), ip=client_ip(request))
    db.commit()
    return _detail(db, catalog_service.get_lot(db, lot_id))


@router.post(
    "/lots/{lot_id}/withdraw",
    response_model=LotDetailOut,
    operation_id="lots_withdraw",
)
def withdraw_lot(
    lot_id: str, body: NoteIn, principal: CurrentBrand, db: Db, request: Request
) -> LotDetailOut:
    """Pull a lot out of the catalogue for good. Not a delete."""
    lot = _owned(db, principal, lot_id)
    approval_service.withdraw(
        db, lot=lot, actor=_actor(db, principal), note=body.note, ip=client_ip(request)
    )
    db.commit()
    return _detail(db, catalog_service.get_lot(db, lot_id))


@router.put(
    "/lots/{lot_id}/visibility",
    response_model=LotDetailOut,
    operation_id="lots_set_visibility",
)
def set_visibility(
    lot_id: str,
    body: VisibilityIn,
    principal: CurrentBrand,
    db: Db,
    request: Request,
) -> LotDetailOut:
    """Change the protection level. Allowed while the lot is live."""
    lot = _owned(db, principal, lot_id)
    approval_service.set_visibility(
        db,
        lot=lot,
        actor=_actor(db, principal),
        visibility=body.visibility,
        ip=client_ip(request),
    )
    db.commit()
    return _detail(db, catalog_service.get_lot(db, lot_id))


@router.put(
    "/lots/{lot_id}/region-lock",
    response_model=LotDetailOut,
    operation_id="lots_set_region_lock",
)
def set_region_lock(
    lot_id: str,
    body: RegionLockIn,
    principal: CurrentBrand,
    db: Db,
    request: Request,
) -> LotDetailOut:
    """Replace this lot's excluded cities, overriding the brand default."""
    lot = _owned(db, principal, lot_id)
    approval_service.set_region_lock(
        db,
        lot=lot,
        actor=_actor(db, principal),
        cities=body.cities,
        ip=client_ip(request),
    )
    db.commit()
    return _detail(db, catalog_service.get_lot(db, lot_id))


@router.get(
    "/lots/{lot_id}/approvals",
    response_model=list[ApprovalOut],
    operation_id="lots_approval_trail",
)
def approval_trail(lot_id: str, principal: CurrentBrand, db: Db) -> list[ApprovalOut]:
    """Every decision ever recorded against this lot, oldest first.

    Append only, enforced by a database trigger, so this is what happened
    rather than what the current state implies.
    """
    _owned(db, principal, lot_id)
    return [
        ApprovalOut.model_validate(entry)
        for entry in approval_service.approval_trail(db, lot_id=lot_id)
    ]


# ------------------------------------------------------------------- browsing


@router.get(
    "/catalog",
    response_model=BrowseOut,
    operation_id="catalog_browse",
)
def browse_catalog(
    principal: CurrentPrincipal,
    db: Db,
    city: Annotated[str | None, Query(max_length=80)] = None,
    category_id: Annotated[str | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 24,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> BrowseOut:
    """The buyer facing catalogue.

    The only endpoint here that does not check ownership. It applies the
    visibility rules instead: live and approved only, private lots for
    verified resellers only, and the region lock against `city`.

    `city` defaults to the reseller's own city and can be overridden, because
    a reseller in Karachi legitimately buys for a shop in Multan. The region
    lock applies to whichever city is being bought for, which is the thing the
    brand is protecting.
    """
    user = db.get(User, principal.user_id)
    profile = user.reseller_profile if user is not None else None
    verified = (
        profile is not None and VerificationStatus(profile.status) == VerificationStatus.VERIFIED
    )
    if city is None and profile is not None:
        city = profile.city

    rows, total = approval_service.browse(
        db,
        role=principal.role,
        reseller_is_verified=verified or principal.is_admin,
        city=city,
        category_id=category_id,
        limit=limit,
        offset=offset,
    )

    items: list[BrowseItemOut] = []
    for lot in rows:
        shown = approval_service.present(db, lot, viewer_role=principal.role)
        items.append(
            BrowseItemOut(
                lot=LotOut.model_validate(lot),
                brand_name=shown.brand_name,
                brand_is_hidden=shown.brand_is_hidden,
            )
        )
    return BrowseOut(items=items, total=total, limit=limit, offset=offset)
