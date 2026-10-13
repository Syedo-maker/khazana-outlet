"""Brand portal endpoints.

Who may call what, stated once here because it is the whole security model of
this router:

- A brand user acts only on brands they belong to, enforced by `assert_owns`,
  which answers 404 rather than 403 so probing identifiers reveals nothing.
- Verification decisions and suspension are admin only, enforced in the
  service layer as well, so a new caller cannot bypass them by skipping the
  dependency.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, File, Form, Request, UploadFile, status
from pydantic import BaseModel, ConfigDict, Field

from ...core.errors import AppError, NotFound
from ...core.tenancy import assert_owns
from ...models import Brand, User
from ...models.enums import DocumentType, UserRole, VerificationStatus, Visibility
from ...services import brand_service
from ..deps import AdminOnly, CurrentBrand, CurrentPrincipal, Db, client_ip

router = APIRouter(prefix="/brands", tags=["brands"])


# ------------------------------------------------------------------ schemas


class BrandRegisterIn(BaseModel):
    name: str = Field(min_length=2, max_length=160)
    city: str = Field(min_length=2, max_length=80)
    legal_name: str | None = Field(default=None, max_length=200)
    ntn: str | None = Field(default=None, max_length=32)
    contact_email: str | None = Field(default=None, max_length=255)


class BrandOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    slug: str
    city: str
    status: VerificationStatus
    legal_name: str | None = None
    ntn: str | None = None
    unbranded_label: str | None = None
    review_note: str | None = None


class PolicyOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    commission_percent: float
    payout_terms_days: int
    min_lot_value_pkr: int
    min_discount_percent: float
    max_discount_percent: float
    default_visibility: Visibility
    require_brand_approval: bool
    allow_cod: bool
    allow_part_lot_orders: bool
    auto_apply_ai_draft: bool
    ai_monthly_budget_usd: float


class PolicyUpdateIn(BaseModel):
    """Every field optional. Only what is sent is changed.

    `require_brand_approval` is deliberately absent. It is pinned true in the
    schema, and offering it here would promise something the database refuses.
    """

    model_config = ConfigDict(extra="forbid")

    commission_percent: float | None = Field(default=None, ge=0, le=50)
    payout_terms_days: int | None = Field(default=None, ge=0, le=90)
    min_lot_value_pkr: int | None = Field(default=None, ge=0)
    min_discount_percent: float | None = Field(default=None, ge=0, le=95)
    max_discount_percent: float | None = Field(default=None, ge=0, le=95)
    default_visibility: Visibility | None = None
    allow_cod: bool | None = None
    allow_part_lot_orders: bool | None = None
    auto_apply_ai_draft: bool | None = None
    ai_monthly_budget_usd: float | None = Field(default=None, ge=0)


class DocumentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    doc_type: DocumentType
    status: VerificationStatus
    original_filename: str | None = None
    size_bytes: int | None = None
    review_note: str | None = None


class DashboardOut(BaseModel):
    brand: BrandOut
    policy: PolicyOut
    documents_supplied: list[DocumentType]
    documents_missing: list[DocumentType]
    can_request_verification: bool
    is_verified: bool
    lots_by_status: dict[str, int]
    live_lots: int
    orders_this_month: int
    awaiting_payout_pkr: int


class ReviewIn(BaseModel):
    approve: bool
    note: str | None = Field(default=None, max_length=500)


class SuspendIn(BaseModel):
    reason: str = Field(min_length=3, max_length=500)


class RegionLockIn(BaseModel):
    cities: list[str] = Field(default_factory=list, max_length=60)


# ----------------------------------------------------------------- endpoints


@router.post(
    "",
    operation_id="brands_register",
    summary="Register a brand",
    status_code=status.HTTP_201_CREATED,
    response_model=BrandOut,
    responses={409: {"description": "A brand with that web address already exists"}},
)
def register_brand(
    payload: BrandRegisterIn, principal: CurrentPrincipal, db: Db, request: Request
) -> BrandOut:
    """Create a brand, its policy row and the caller's membership.

    The caller becomes a brand user, because otherwise they would register a
    brand and immediately be unable to see it.
    """
    user = db.get(User, principal.user_id)
    if user is None:
        raise NotFound("That account no longer exists.").as_http()

    try:
        brand = brand_service.register_brand(
            db,
            owner=user,
            name=payload.name,
            city=payload.city,
            legal_name=payload.legal_name,
            ntn=payload.ntn,
            contact_email=payload.contact_email,
            ip=client_ip(request),
        )
    except AppError as exc:
        raise exc.as_http() from exc

    db.commit()
    return BrandOut.model_validate(brand)


@router.get(
    "/{brand_id}/dashboard",
    operation_id="brands_dashboard",
    summary="Everything the brand portal home screen needs",
    response_model=DashboardOut,
    responses={404: {"description": "No such brand, or it belongs to someone else"}},
)
def dashboard(brand_id: str, principal: CurrentBrand, db: Db) -> DashboardOut:
    assert_owns(principal, brand_id)

    try:
        view = brand_service.dashboard(db, brand_id)
    except AppError as exc:
        raise exc.as_http() from exc

    return DashboardOut(
        brand=BrandOut.model_validate(view.brand),
        policy=PolicyOut.model_validate(view.policy),
        documents_supplied=view.documents_supplied,
        documents_missing=view.documents_missing,
        can_request_verification=view.can_request_verification,
        is_verified=view.is_verified,
        lots_by_status=view.lots_by_status,
        live_lots=view.live_lots,
        orders_this_month=view.orders_this_month,
        awaiting_payout_pkr=view.awaiting_payout_pkr,
    )


@router.post(
    "/{brand_id}/documents",
    operation_id="brands_upload_document",
    summary="Upload a verification document",
    status_code=status.HTTP_201_CREATED,
    response_model=DocumentOut,
    responses={
        404: {"description": "No such brand, or it belongs to someone else"},
        409: {"description": "The brand is already verified"},
        422: {"description": "The file is not a PDF or image, or does not match its type"},
    },
)
async def upload_document(
    brand_id: str,
    principal: CurrentBrand,
    db: Db,
    request: Request,
    doc_type: Annotated[DocumentType, Form()],
    file: Annotated[UploadFile, File(description="PDF, JPEG or PNG, up to 10 MB")],
) -> DocumentOut:
    """Store one document. Replacing a document resets its review.

    An admin who already approved the previous file has not seen the new one.
    """
    assert_owns(principal, brand_id)

    user = db.get(User, principal.user_id)
    if user is None:
        raise NotFound("That account no longer exists.").as_http()

    data = await file.read()
    try:
        document = brand_service.upload_document(
            db,
            brand_id=brand_id,
            doc_type=doc_type,
            data=data,
            filename=file.filename or "document",
            content_type=file.content_type or "",
            uploaded_by=user,
            ip=client_ip(request),
        )
    except AppError as exc:
        raise exc.as_http() from exc

    db.commit()
    return DocumentOut.model_validate(document)


@router.post(
    "/{brand_id}/request-verification",
    operation_id="brands_request_verification",
    summary="Submit the brand for admin review",
    response_model=BrandOut,
    responses={
        403: {"description": "The brand is suspended"},
        409: {"description": "The brand is already verified"},
        422: {"description": "Required documents are still missing"},
    },
)
def request_verification(
    brand_id: str, principal: CurrentBrand, db: Db, request: Request
) -> BrandOut:
    assert_owns(principal, brand_id)

    user = db.get(User, principal.user_id)
    if user is None:
        raise NotFound("That account no longer exists.").as_http()

    try:
        brand = brand_service.request_verification(
            db, brand_id=brand_id, requested_by=user, ip=client_ip(request)
        )
    except AppError as exc:
        raise exc.as_http() from exc

    db.commit()
    return BrandOut.model_validate(brand)


@router.patch(
    "/{brand_id}/policy",
    operation_id="brands_update_policy",
    summary="Change the brand's commercial terms",
    response_model=PolicyOut,
    responses={
        404: {"description": "No such brand, or it belongs to someone else"},
        422: {"description": "An inverted discount band, or a field that cannot be changed"},
    },
)
def update_policy(
    brand_id: str,
    payload: PolicyUpdateIn,
    principal: CurrentBrand,
    db: Db,
    request: Request,
) -> PolicyOut:
    """Commission, discount band, payout terms and lot minimum are all data.

    Brand approval is not offered here. It is pinned true in the schema,
    because the protection it gives is the reason a brand is willing to list.
    """
    assert_owns(principal, brand_id)

    changes = payload.model_dump(exclude_unset=True, exclude_none=True)
    if not changes:
        raise AppError("Send at least one setting to change.").as_http()

    user = db.get(User, principal.user_id)
    if user is None:
        raise NotFound("That account no longer exists.").as_http()

    try:
        policy = brand_service.update_policy(
            db, brand_id=brand_id, actor=user, changes=changes, ip=client_ip(request)
        )
    except AppError as exc:
        raise exc.as_http() from exc

    db.commit()
    return PolicyOut.model_validate(policy)


@router.put(
    "/{brand_id}/region-lock",
    operation_id="brands_set_region_lock",
    summary="Replace the cities this brand excludes by default",
    response_model=list[str],
)
def set_region_lock(
    brand_id: str,
    payload: RegionLockIn,
    principal: CurrentBrand,
    db: Db,
    request: Request,
) -> list[str]:
    """Cities every new lot inherits as excluded. A lot can still override."""
    assert_owns(principal, brand_id)

    user = db.get(User, principal.user_id)
    if user is None:
        raise NotFound("That account no longer exists.").as_http()

    try:
        cities = brand_service.set_excluded_cities(
            db, brand_id=brand_id, cities=payload.cities, actor=user, ip=client_ip(request)
        )
    except AppError as exc:
        raise exc.as_http() from exc

    db.commit()
    return cities


# --------------------------------------------------------------- admin only


@router.get(
    "/admin/verification-queue",
    operation_id="brands_verification_queue",
    summary="Brands waiting for an admin decision",
    response_model=list[BrandOut],
)
def verification_queue(principal: AdminOnly, db: Db) -> list[BrandOut]:
    """Oldest first, because a brand waiting longest has waited longest."""
    from sqlalchemy import select

    brands = db.scalars(
        select(Brand)
        .where(Brand.status == VerificationStatus.PENDING, Brand.deleted_at.is_(None))
        .order_by(Brand.created_at)
        .limit(100)
    ).all()
    return [BrandOut.model_validate(brand) for brand in brands]


@router.post(
    "/{brand_id}/review",
    operation_id="brands_review",
    summary="Approve or reject a brand",
    response_model=BrandOut,
    responses={
        403: {"description": "Only an admin can verify a brand"},
        422: {"description": "A rejection with no reason, or documents still missing"},
    },
)
def review_brand(
    brand_id: str,
    payload: ReviewIn,
    principal: AdminOnly,
    db: Db,
    request: Request,
) -> BrandOut:
    """A rejection must carry a reason, so the brand can fix it."""
    admin = db.get(User, principal.user_id)
    if admin is None or admin.role != UserRole.ADMIN:
        raise NotFound("That account no longer exists.").as_http()

    try:
        brand = brand_service.review_brand(
            db,
            brand_id=brand_id,
            admin=admin,
            approve=payload.approve,
            note=payload.note,
            ip=client_ip(request),
        )
    except AppError as exc:
        raise exc.as_http() from exc

    db.commit()
    return BrandOut.model_validate(brand)


@router.post(
    "/{brand_id}/suspend",
    operation_id="brands_suspend",
    summary="Suspend a brand and pause its live listings",
    response_model=BrandOut,
    responses={403: {"description": "Only an admin can suspend a brand"}},
)
def suspend_brand(
    brand_id: str,
    payload: SuspendIn,
    principal: AdminOnly,
    db: Db,
    request: Request,
) -> BrandOut:
    """Live listings are paused too, or a suspended brand keeps taking orders."""
    admin = db.get(User, principal.user_id)
    if admin is None or admin.role != UserRole.ADMIN:
        raise NotFound("That account no longer exists.").as_http()

    try:
        brand = brand_service.suspend_brand(
            db,
            brand_id=brand_id,
            admin=admin,
            reason=payload.reason,
            ip=client_ip(request),
        )
    except AppError as exc:
        raise exc.as_http() from exc

    db.commit()
    return BrandOut.model_validate(brand)
