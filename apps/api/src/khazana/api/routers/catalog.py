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

from dataclasses import asdict
from datetime import date
from typing import Annotated, Any, Literal, cast

from fastapi import APIRouter, File, Form, Query, Request, Response, UploadFile, status
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from ...ai import images
from ...ai.logo_regions import Box
from ...core.errors import NotFound, ValidationFailed
from ...core.tenancy import assert_owns
from ...models import BrandPolicy, Lot, LotPhoto, User
from ...models.enums import (
    ConditionGrade,
    LotStatus,
    PhotoKind,
    PhotoProtectionStatus,
    SettlementMode,
    VerificationStatus,
    Visibility,
)
from ...services import (
    approval_service,
    bargaining_service,
    catalog_service,
    order_service,
    photo_protection_service,
    profit_service,
    size_service,
)
from ...storage import put_object, read_object, thumbnail_key
from ..deps import CurrentBrand, CurrentPrincipal, Db, Principal, client_ip
from ..uploads import read_upload

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


class ProtectionRegionIn(BaseModel):
    """An area to hide, as fractions of the image."""

    model_config = ConfigDict(extra="forbid")

    x: float = Field(ge=0, le=1)
    y: float = Field(ge=0, le=1)
    width: float = Field(gt=0, le=1)
    height: float = Field(gt=0, le=1)


class PhotoReviewIn(BaseModel):
    """Null accepts the current result. An empty list means no brand mark."""

    model_config = ConfigDict(extra="forbid")

    regions: list[ProtectionRegionIn] | None = Field(default=None, max_length=24)


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
    protection_status: PhotoProtectionStatus
    has_protected_copy: bool = False
    protection_reviewed: bool = False
    protection_detail: dict[str, Any] | None = None

    @model_validator(mode="wrap")
    @classmethod
    def _protection_flags(cls, value: Any, handler: Any) -> PhotoOut:
        photo: PhotoOut = handler(value)
        if isinstance(value, LotPhoto):
            photo.has_protected_copy = value.blurred_file_key is not None
            photo.protection_reviewed = value.protection_reviewed_at is not None
        return photo


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
    reserved_pieces: int
    available_pieces: int
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
    # The per lot switches for the value band agents. Null inherits the brand.
    bargaining_enabled: bool | None = None
    auto_markdown_enabled: bool | None = None


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


class CatalogLotOut(BaseModel):
    """A listing for buyers.

    It has no brand identifier. Even an opaque id would let a buyer group an
    unbranded brand's lots together and match them to its named ones.
    """

    model_config = ConfigDict(from_attributes=True)

    id: str
    lot_code: str
    category_id: str
    title: str
    description: str | None = None
    season: str | None = None
    condition_grade: ConditionGrade
    total_pieces: int
    available_pieces: int
    retail_price_per_piece_pkr: int
    lot_price_pkr: int
    min_order_pieces: int
    stock_city: str
    status: LotStatus
    visibility: Visibility
    expiry_date: date | None = None
    available_until: date | None = None
    price_per_piece_pkr: float
    discount_percent: float


class CatalogPhotoOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    kind: PhotoKind
    sort_order: int
    width: int | None = None
    height: int | None = None


class CatalogDefectOut(BaseModel):
    issue: str
    pieces_affected: int
    photo_id: str | None = None


class CatalogManifestLineOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    size: str
    color: str
    pieces: int


class CatalogAvailableLineOut(BaseModel):
    size: str
    color: str
    pieces: int


class BrowseItemOut(BaseModel):
    """A listing as one viewer may see it.

    `brand_name` is whatever that viewer is allowed to know: the real name, or
    the unbranded label. The real name is never in this payload for an
    unbranded lot, because filtering it in the client would mean shipping it
    to the client first.
    """

    lot: CatalogLotOut
    brand_name: str
    brand_is_hidden: bool
    cover_photo_id: str | None = None


class SizeGuideOut(BaseModel):
    size: str
    standard: str | None
    match: str
    measurements: str


class CatalogDetailOut(BrowseItemOut):
    photos: list[CatalogPhotoOut]
    manifest_lines: list[CatalogManifestLineOut]
    available_lines: list[CatalogAvailableLineOut]
    allows_part_lot: bool
    allows_cod: bool
    # Cash on delivery to the brand's own courier is the only way to pay.
    pays_brand_directly: bool = False
    allows_pooling: bool = False
    allows_bargaining: bool = False
    size_guide: list[SizeGuideOut] = Field(default_factory=list)
    defects: list[CatalogDefectOut]


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


def _photo_on(lot: Lot, photo_id: str) -> LotPhoto:
    photo = next((item for item in lot.photos if item.id == photo_id), None)
    if photo is None:
        raise NotFound("That photograph is not on this lot.")
    return photo


def _image_response(key: str, size: str = "full") -> Response:
    """A stored photograph, or its thumbnail, made on first request and kept.

    The thumbnail is keyed off the photograph's own storage key, so a new
    protected copy gets a new thumbnail, and deleting the photograph deletes
    its thumbnail with it.
    """
    try:
        if size == "thumb":
            small = thumbnail_key(key)
            try:
                data = read_object(small)
            except FileNotFoundError:
                data = images.thumbnail(read_object(key))
                put_object(small, data, "image/jpeg")
        else:
            data = read_object(key)
    except FileNotFoundError:
        raise NotFound("That photograph is not available.") from None
    return Response(
        content=data,
        media_type="image/jpeg",
        # Private, because every one of these sits behind a sign in.
        headers={"Cache-Control": "private, max-age=300"},
    )


def _buyer_view(db: Session, principal: Principal, city: str | None) -> tuple[bool, str | None]:
    """Whether this viewer counts as verified, and the city being bought for."""
    user = db.get(User, principal.user_id)
    profile = user.reseller_profile if user is not None else None
    verified = (
        profile is not None and VerificationStatus(profile.status) == VerificationStatus.VERIFIED
    )
    if city is None and profile is not None:
        city = profile.city
    return verified or principal.is_admin, city


def _browse_item(db: Session, principal: Principal, lot: Lot) -> BrowseItemOut:
    shown = approval_service.present(
        db, lot, viewer_role=principal.role, viewer_brand_ids=principal.brand_ids
    )
    photos = photo_protection_service.buyer_photos(lot)
    return BrowseItemOut(
        lot=CatalogLotOut.model_validate(lot),
        brand_name=shown.brand_name,
        brand_is_hidden=shown.brand_is_hidden,
        cover_photo_id=photos[0].id if photos else None,
    )


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
    data = await read_upload(file)

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
    data = await read_upload(file)

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


@router.get(
    "/lots/{lot_id}/photos/{photo_id}/image",
    operation_id="lots_photo_image",
    response_class=Response,
)
def owner_photo_image(
    lot_id: str,
    photo_id: str,
    principal: CurrentBrand,
    db: Db,
    variant: Annotated[Literal["original", "protected"], Query()] = "original",
    size: Annotated[Literal["full", "thumb"], Query()] = "full",
) -> Response:
    """A photograph for its owner, either as uploaded or as buyers would see it."""
    photo = _photo_on(_owned(db, principal, lot_id), photo_id)
    key = photo.file_key if variant == "original" else photo.blurred_file_key
    if key is None:
        raise NotFound("This photograph has no protected copy.")
    return _image_response(key, size)


@router.post(
    "/lots/{lot_id}/photos/protection/scan",
    response_model=list[PhotoOut],
    operation_id="lots_scan_photos_for_marks",
)
def scan_photos(lot_id: str, principal: CurrentBrand, db: Db, request: Request) -> list[PhotoOut]:
    """Look for brand marks on an unbranded lot. One paid model call per new photo."""
    lot = _owned(db, principal, lot_id)
    photos = photo_protection_service.scan_lot(
        db, lot=lot, actor=_actor(db, principal), ip=client_ip(request)
    )
    db.commit()
    return [PhotoOut.model_validate(photo) for photo in photos]


@router.put(
    "/lots/{lot_id}/photos/{photo_id}/protection",
    response_model=PhotoOut,
    operation_id="lots_review_photo_protection",
)
def review_photo_protection(
    lot_id: str,
    photo_id: str,
    body: PhotoReviewIn,
    principal: CurrentBrand,
    db: Db,
    request: Request,
) -> PhotoOut:
    """Accept a result, or choose exactly which areas buyers must not see."""
    lot = _owned(db, principal, lot_id)
    regions = (
        None if body.regions is None else [Box(r.x, r.y, r.width, r.height) for r in body.regions]
    )
    photo = photo_protection_service.review_photo(
        db,
        lot=lot,
        photo_id=photo_id,
        actor=_actor(db, principal),
        regions=regions,
        ip=client_ip(request),
    )
    db.commit()
    return PhotoOut.model_validate(photo)


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
    verified, city = _buyer_view(db, principal, city)
    rows, total = approval_service.browse(
        db,
        role=principal.role,
        reseller_is_verified=verified,
        city=city,
        category_id=category_id,
        limit=limit,
        offset=offset,
    )
    approval_service.preload_brands(db, rows)
    items = [_browse_item(db, principal, lot) for lot in rows]
    return BrowseOut(items=items, total=total, limit=limit, offset=offset)


def _catalog_lot(db: Session, principal: Principal, lot_id: str, city: str | None) -> Lot:
    verified, city = _buyer_view(db, principal, city)
    return approval_service.visible_lot(
        db,
        lot_id=lot_id,
        role=principal.role,
        reseller_is_verified=verified,
        city=city,
    )


@router.get(
    "/catalog/{lot_id}",
    response_model=CatalogDetailOut,
    operation_id="catalog_detail",
)
def catalog_detail(
    lot_id: str,
    principal: CurrentPrincipal,
    db: Db,
    city: Annotated[str | None, Query(max_length=80)] = None,
) -> CatalogDetailOut:
    """One listing, under the same rules as the catalogue."""
    lot = _catalog_lot(db, principal, lot_id, city)
    item = _browse_item(db, principal, lot)
    photos = photo_protection_service.buyer_photos(lot)
    shown_ids = {photo.id for photo in photos}
    policy = db.scalars(select(BrandPolicy).where(BrandPolicy.brand_id == lot.brand_id)).first()
    direct = policy is not None and SettlementMode(policy.settlement_mode) == SettlementMode.DIRECT
    return CatalogDetailOut(
        **item.model_dump(),
        photos=[CatalogPhotoOut.model_validate(photo) for photo in photos],
        manifest_lines=[CatalogManifestLineOut.model_validate(x) for x in lot.manifest_lines],
        available_lines=[
            CatalogAvailableLineOut(size=line.size, color=line.color, pieces=line.pieces)
            for line in order_service.available_lines(db, lot)
        ],
        allows_part_lot=bool(policy and policy.allow_part_lot_orders),
        allows_cod=bool(policy and (policy.allow_cod or direct)),
        pays_brand_directly=direct,
        allows_pooling=bool(policy and policy.allow_pooled_orders),
        allows_bargaining=bargaining_service.bargaining_allowed(lot, policy),
        size_guide=[SizeGuideOut(**asdict(g)) for g in size_service.guide_for(db, lot)],
        defects=[
            CatalogDefectOut(
                issue=defect.issue,
                pieces_affected=defect.pieces_affected,
                # A defect must not point at a photograph being withheld.
                photo_id=defect.photo_id if defect.photo_id in shown_ids else None,
            )
            for defect in lot.defects
        ],
    )


class ProfitScenarioOut(BaseModel):
    name: str
    price_per_piece_pkr: int
    revenue_pkr: int
    profit_pkr: int
    margin_percent: float


class ProfitOut(BaseModel):
    lot_code: str
    city: str
    pieces: int
    goods_pkr: int
    shipping_pkr: int | None
    cost_pkr: int
    cost_per_piece_pkr: int
    scenarios: list[ProfitScenarioOut]
    break_even_pieces: int | None
    benchmark: str
    assumptions: list[str]


@router.get(
    "/catalog/{lot_id}/profit",
    response_model=ProfitOut,
    operation_id="catalog_profit_estimate",
    responses={404: {"description": "No such listing for this viewer"}},
)
def profit_estimate(
    lot_id: str,
    principal: CurrentPrincipal,
    db: Db,
    city: Annotated[str | None, Query(max_length=80)] = None,
    pieces: Annotated[int | None, Query(ge=1)] = None,
    selling_price_pkr: Annotated[int | None, Query(ge=1)] = None,
) -> ProfitOut:
    """What this lot could make if resold in the buyer's city.

    An estimate from the real delivery quote and an administrator maintained
    resale benchmark, with every assumption listed. It is not a promise.
    """
    lot = _catalog_lot(db, principal, lot_id, city)
    _, resolved_city = _buyer_view(db, principal, city)
    result = profit_service.estimate(
        db,
        lot=lot,
        city=resolved_city or lot.stock_city,
        pieces=pieces,
        selling_price_pkr=selling_price_pkr,
    )
    return ProfitOut(
        lot_code=result.lot_code,
        city=result.city,
        pieces=result.pieces,
        goods_pkr=result.goods_pkr,
        shipping_pkr=result.shipping_pkr,
        cost_pkr=result.cost_pkr,
        cost_per_piece_pkr=result.cost_per_piece_pkr,
        scenarios=[ProfitScenarioOut(**asdict(s)) for s in result.scenarios],
        break_even_pieces=result.break_even_pieces,
        benchmark=result.benchmark,
        assumptions=result.assumptions,
    )


@router.get(
    "/catalog/{lot_id}/photos/{photo_id}",
    operation_id="catalog_photo_image",
    response_class=Response,
)
def catalog_photo_image(
    lot_id: str,
    photo_id: str,
    principal: CurrentPrincipal,
    db: Db,
    city: Annotated[str | None, Query(max_length=80)] = None,
    size: Annotated[Literal["full", "thumb"], Query()] = "full",
) -> Response:
    """A photograph as buyers may see it, and never the original of a protected one.

    ``size=thumb`` is a 400 pixel copy for catalogue cards.
    """
    lot = _catalog_lot(db, principal, lot_id, city)
    key = photo_protection_service.buyer_file_key(lot, _photo_on(lot, photo_id))
    if key is None:
        raise NotFound("That photograph is not available.")
    return _image_response(key, size)
