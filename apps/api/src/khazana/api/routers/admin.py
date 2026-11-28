"""The admin panel's API. Every route here requires an admin."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Query, Request, Response, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from ...core.errors import NotFound
from ...models import (
    AuditLog,
    Brand,
    BrandPolicy,
    Courier,
    Dispute,
    Payment,
    Payout,
    PayoutRun,
    ResellerProfile,
    ShippingRate,
    User,
    VerificationDocument,
)
from ...models.enums import (
    DisputeStatus,
    DocumentType,
    LotStatus,
    PaymentMethod,
    PaymentStatus,
    PayoutStatus,
    SettlementMode,
    VerificationStatus,
)
from ...services import (
    admin_service,
    brand_service,
    catalog_service,
    order_service,
    payment_service,
    profit_service,
)
from ...storage import read_object
from ..deps import AdminOnly, Db, Principal, client_ip
from .brands import BrandOut, PolicyOut
from .catalog import LotOut

router = APIRouter(prefix="/admin", tags=["admin"])


class ReviewIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    approve: bool
    note: str | None = Field(default=None, max_length=500)


class ResellerReviewOut(BaseModel):
    id: str
    user_id: str
    full_name: str
    phone: str
    business_name: str
    city: str
    ntn: str | None
    shop_address: str | None
    monthly_purchase_pkr: int | None
    status: VerificationStatus
    review_note: str | None
    created_at: datetime


class DocumentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    doc_type: DocumentType
    status: VerificationStatus
    original_filename: str | None
    content_type: str | None


class AdminBrandOut(BaseModel):
    brand: BrandOut
    policy: PolicyOut
    documents: list[DocumentOut]


class CommercialTermsIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    commission_percent: float | None = Field(default=None, ge=0, le=50)
    payout_terms_days: int | None = Field(default=None, ge=0, le=90)
    # direct: cash on delivery to the brand, commission invoiced monthly.
    # platform: paid to the platform and paid out. Existing orders keep theirs.
    settlement_mode: SettlementMode | None = None


class ModerationItemOut(BaseModel):
    lot: LotOut
    brand_name: str
    risk_score: int
    risk_band: str
    findings: list[str]


class TakeDownIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    note: str = Field(min_length=10, max_length=500)
    withdraw: bool = False


class AdminPaymentOut(BaseModel):
    id: str
    order_id: str
    method: PaymentMethod
    status: PaymentStatus
    amount_pkr: int
    refunded_pkr: int
    provider: str | None
    provider_reference: str | None
    failure_reason: str | None
    created_at: datetime


class ReconciliationOut(BaseModel):
    kind: str
    payment_id: str
    order_code: str
    amount_pkr: int
    detail: str


class RefundIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    note: str = Field(min_length=10, max_length=500)


class AdminDisputeOut(BaseModel):
    id: str
    order_id: str
    order_code: str
    total_pkr: int
    reason: str
    detail: str | None
    status: DisputeStatus
    resolution: str | None
    refund_pkr: int | None
    created_at: datetime


class ResolveDisputeIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    resolution: str = Field(min_length=10, max_length=4_000)
    refund_pkr: int = Field(default=0, ge=0)


class PayoutOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    order_id: str
    brand_id: str
    amount_pkr: int
    status: PayoutStatus
    scheduled_for: datetime | None
    paid_at: datetime | None
    reference: str | None
    run_id: str | None


class PayoutRunIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    payout_ids: list[str] | None = Field(default=None, max_length=500)


class PayoutRunOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    status: PayoutStatus
    payout_count: int
    total_pkr: int
    reference: str | None
    paid_at: datetime | None
    created_at: datetime


class PayoutRunPaidIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reference: str = Field(min_length=3, max_length=120)


class ShippingRateOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    origin_city: str | None
    destination_city: str | None
    base_pkr: int
    per_kg_pkr: int
    default_piece_grams: int
    is_active: bool


class CourierOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    code: str
    name: str
    is_active: bool
    is_default: bool
    rates: list[ShippingRateOut]


class CourierUpdateIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    is_active: bool | None = None
    is_default: bool | None = None


class ShippingRateIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    origin_city: str | None = Field(default=None, max_length=80)
    destination_city: str | None = Field(default=None, max_length=80)
    base_pkr: int = Field(ge=0)
    per_kg_pkr: int = Field(ge=0)
    default_piece_grams: int = Field(default=300, gt=0)
    is_active: bool = True


class ShippingRateUpdateIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    base_pkr: int | None = Field(default=None, ge=0)
    per_kg_pkr: int | None = Field(default=None, ge=0)
    default_piece_grams: int | None = Field(default=None, gt=0)
    is_active: bool | None = None


class AuditEntryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    actor_user_id: str | None
    actor_role: str | None
    actor_kind: str
    action: str
    entity_type: str
    entity_id: str | None
    brand_id: str | None
    before: dict[str, Any] | None
    after: dict[str, Any] | None
    note: str | None
    created_at: datetime


def _admin(db: Session, principal: Principal) -> User:
    user = db.get(User, principal.user_id)
    if user is None:
        raise NotFound("That account no longer exists.")
    return user


def _reseller_out(profile: ResellerProfile) -> ResellerReviewOut:
    return ResellerReviewOut(
        id=profile.id,
        user_id=profile.user_id,
        full_name=profile.user.full_name,
        phone=profile.user.phone,
        business_name=profile.business_name,
        city=profile.city,
        ntn=profile.ntn,
        shop_address=profile.shop_address,
        monthly_purchase_pkr=profile.monthly_purchase_pkr,
        status=profile.status,
        review_note=profile.review_note,
        created_at=profile.created_at,
    )


def _payment_out(payment: Payment) -> AdminPaymentOut:
    return AdminPaymentOut(
        id=payment.id,
        order_id=payment.order_id,
        method=payment.method,
        status=payment.status,
        amount_pkr=payment.amount_pkr,
        refunded_pkr=payment.refunded_pkr,
        provider=payment.provider,
        provider_reference=payment.provider_reference,
        failure_reason=payment.failure_reason,
        created_at=payment.created_at,
    )


def _dispute_out(dispute: Dispute) -> AdminDisputeOut:
    return AdminDisputeOut(
        id=dispute.id,
        order_id=dispute.order_id,
        order_code=dispute.order.order_code,
        total_pkr=dispute.order.total_pkr,
        reason=dispute.reason,
        detail=dispute.detail,
        status=dispute.status,
        resolution=dispute.resolution,
        refund_pkr=dispute.refund_pkr,
        created_at=dispute.created_at,
    )


def _brand_out(db: Session, brand: Brand) -> AdminBrandOut:
    policy = db.scalars(select(BrandPolicy).where(BrandPolicy.brand_id == brand.id)).one()
    return AdminBrandOut(
        brand=BrandOut.model_validate(brand),
        policy=PolicyOut.model_validate(policy),
        documents=[DocumentOut.model_validate(document) for document in brand.documents],
    )


@router.get("/overview", operation_id="admin_overview")
def overview(principal: AdminOnly, db: Db) -> dict[str, Any]:
    return admin_service.overview(db)


# ---------------------------------------------------------------- verification


@router.get(
    "/resellers",
    response_model=list[ResellerReviewOut],
    operation_id="admin_resellers",
)
def resellers(
    principal: AdminOnly,
    db: Db,
    review_status: Annotated[VerificationStatus, Query(alias="status")] = (
        VerificationStatus.PENDING
    ),
) -> list[ResellerReviewOut]:
    rows = admin_service.resellers_for_review(db, status=review_status)
    return [_reseller_out(row) for row in rows]


@router.post(
    "/resellers/{profile_id}/review",
    response_model=ResellerReviewOut,
    operation_id="admin_review_reseller",
)
def review_reseller(
    profile_id: str, body: ReviewIn, principal: AdminOnly, db: Db, request: Request
) -> ResellerReviewOut:
    profile = admin_service.review_reseller(
        db,
        profile_id=profile_id,
        admin=_admin(db, principal),
        approve=body.approve,
        note=body.note,
        ip=client_ip(request),
    )
    db.commit()
    return _reseller_out(profile)


@router.get("/brands", response_model=list[AdminBrandOut], operation_id="admin_brands")
def brands(
    principal: AdminOnly,
    db: Db,
    brand_status: Annotated[VerificationStatus | None, Query(alias="status")] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 100,
) -> list[AdminBrandOut]:
    statement = select(Brand).where(Brand.deleted_at.is_(None)).order_by(Brand.created_at)
    if brand_status is not None:
        statement = statement.where(Brand.status == brand_status)
    return [_brand_out(db, brand) for brand in db.scalars(statement.limit(limit)).all()]


@router.get(
    "/documents/{document_id}",
    operation_id="admin_document_file",
    response_class=Response,
)
def document_file(document_id: str, principal: AdminOnly, db: Db) -> Response:
    document = db.get(VerificationDocument, document_id)
    if document is None:
        raise NotFound("That document does not exist.")
    return Response(
        content=read_object(document.file_key),
        media_type=document.content_type or "application/octet-stream",
        headers={"Cache-Control": "no-store"},
    )


@router.patch(
    "/brands/{brand_id}/terms",
    response_model=AdminBrandOut,
    operation_id="admin_update_brand_terms",
)
def update_terms(
    brand_id: str,
    body: CommercialTermsIn,
    principal: AdminOnly,
    db: Db,
    request: Request,
) -> AdminBrandOut:
    """Change commission or payout terms. Existing orders keep their rate."""
    brand = db.get(Brand, brand_id)
    if brand is None:
        raise NotFound("That brand does not exist.")
    brand_service.update_policy(
        db,
        brand_id=brand_id,
        actor=_admin(db, principal),
        changes=body.model_dump(exclude_none=True),
        ip=client_ip(request),
    )
    db.commit()
    return _brand_out(db, brand)


# ------------------------------------------------------------------ moderation


@router.get(
    "/listings",
    response_model=list[ModerationItemOut],
    operation_id="admin_listings",
)
def listings(
    principal: AdminOnly,
    db: Db,
    lot_status: Annotated[LotStatus | None, Query(alias="status")] = None,
    search: Annotated[str | None, Query(max_length=120)] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[ModerationItemOut]:
    """Listings with their risk score, highest first. The score decides nothing."""
    out: list[ModerationItemOut] = []
    for item in admin_service.moderation_list(
        db, status=lot_status, search=search, limit=limit, offset=offset
    ):
        brand = item.lot.brand
        out.append(
            ModerationItemOut(
                lot=LotOut.model_validate(item.lot),
                brand_name=brand.name if brand else "",
                risk_score=item.risk_score,
                risk_band=item.risk_band,
                findings=item.findings,
            )
        )
    return out


@router.post(
    "/listings/{lot_id}/take-down",
    response_model=LotOut,
    operation_id="admin_take_down_listing",
)
def take_down(
    lot_id: str, body: TakeDownIn, principal: AdminOnly, db: Db, request: Request
) -> LotOut:
    lot = admin_service.take_down(
        db,
        lot=catalog_service.get_lot(db, lot_id),
        admin=_admin(db, principal),
        withdraw=body.withdraw,
        note=body.note,
        ip=client_ip(request),
    )
    db.commit()
    return LotOut.model_validate(lot)


# -------------------------------------------------------------------- payments


@router.get("/payments", response_model=list[AdminPaymentOut], operation_id="admin_payments")
def payments(
    principal: AdminOnly,
    db: Db,
    payment_status: Annotated[PaymentStatus | None, Query(alias="status")] = None,
    method: PaymentMethod | None = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 100,
) -> list[AdminPaymentOut]:
    statement = select(Payment).order_by(Payment.created_at.desc()).limit(limit)
    if payment_status is not None:
        statement = statement.where(Payment.status == payment_status)
    if method is not None:
        statement = statement.where(Payment.method == method)
    return [_payment_out(row) for row in db.scalars(statement).all()]


@router.post(
    "/payments/{payment_id}/confirm-transfer",
    response_model=AdminPaymentOut,
    operation_id="admin_confirm_bank_transfer",
)
def confirm_transfer(
    payment_id: str, principal: AdminOnly, db: Db, request: Request
) -> AdminPaymentOut:
    payment = payment_service.confirm_bank_transfer(
        db,
        payment=payment_service.get_payment(db, payment_id),
        admin=_admin(db, principal),
        ip=client_ip(request),
    )
    db.commit()
    return _payment_out(payment)


@router.get(
    "/reconciliation",
    response_model=list[ReconciliationOut],
    operation_id="admin_reconciliation",
)
def reconciliation(principal: AdminOnly, db: Db) -> list[ReconciliationOut]:
    return [
        ReconciliationOut(
            kind=item.kind,
            payment_id=item.payment_id,
            order_code=item.order_code,
            amount_pkr=item.amount_pkr,
            detail=item.detail,
        )
        for item in payment_service.reconciliation(db)
    ]


@router.post(
    "/orders/{order_id}/refund",
    status_code=status.HTTP_204_NO_CONTENT,
    operation_id="admin_refund_order",
)
def refund_order(
    order_id: str, body: RefundIn, principal: AdminOnly, db: Db, request: Request
) -> None:
    payment_service.refund_order(
        db,
        order=order_service.get_order(db, order_id),
        admin=_admin(db, principal),
        note=body.note,
        ip=client_ip(request),
    )
    db.commit()


@router.post("/jobs/close-dispute-windows", operation_id="admin_close_dispute_windows")
def close_dispute_windows(principal: AdminOnly, db: Db) -> dict[str, int]:
    """Confirm delivered orders whose dispute window has ended."""
    closed = order_service.close_expired_windows(db)
    db.commit()
    return {"closed": closed}


@router.post("/jobs/expire-pools", operation_id="admin_expire_pools")
def expire_pools(principal: AdminOnly, db: Db) -> dict[str, int]:
    """Close committee pools that passed their closing time without being placed.

    Hourly, from the scheduler. Until this ran, an expired pool stayed open.
    """
    from ...services import pool_service

    expired = pool_service.expire_pools(db)
    db.commit()
    return {"expired": expired}


@router.post("/jobs/purge-ai-cache", operation_id="admin_purge_ai_cache")
def purge_ai_cache(principal: AdminOnly, db: Db) -> dict[str, int]:
    """Delete expired entries from the AI response cache. Daily."""
    from ...ai.gateway import response_cache

    purged = response_cache.purge_expired(db)
    db.commit()
    return {"purged": purged}


# -------------------------------------------------------------------- disputes


@router.get("/disputes", response_model=list[AdminDisputeOut], operation_id="admin_disputes")
def disputes(
    principal: AdminOnly,
    db: Db,
    dispute_status: Annotated[DisputeStatus | None, Query(alias="status")] = None,
) -> list[AdminDisputeOut]:
    return [_dispute_out(row) for row in admin_service.disputes(db, status=dispute_status)]


@router.post(
    "/disputes/{dispute_id}/review",
    response_model=AdminDisputeOut,
    operation_id="admin_start_dispute_review",
)
def start_dispute_review(dispute_id: str, principal: AdminOnly, db: Db) -> AdminDisputeOut:
    dispute = admin_service.start_dispute_review(
        db, dispute=admin_service.get_dispute(db, dispute_id), admin=_admin(db, principal)
    )
    db.commit()
    return _dispute_out(dispute)


@router.post(
    "/disputes/{dispute_id}/resolve",
    response_model=AdminDisputeOut,
    operation_id="admin_resolve_dispute",
)
def resolve_dispute(
    dispute_id: str,
    body: ResolveDisputeIn,
    principal: AdminOnly,
    db: Db,
    request: Request,
) -> AdminDisputeOut:
    dispute = admin_service.get_dispute(db, dispute_id)
    payment_service.resolve_dispute(
        db,
        dispute=dispute,
        admin=_admin(db, principal),
        resolution=body.resolution,
        refund_pkr=body.refund_pkr,
        ip=client_ip(request),
    )
    db.commit()
    return _dispute_out(dispute)


# --------------------------------------------------------------------- payouts


@router.get("/payouts", response_model=list[PayoutOut], operation_id="admin_payouts")
def payouts(
    principal: AdminOnly,
    db: Db,
    payout_status: Annotated[PayoutStatus | None, Query(alias="status")] = None,
) -> list[Payout]:
    return admin_service.payouts(db, status=payout_status)


@router.get(
    "/payout-runs",
    response_model=list[PayoutRunOut],
    operation_id="admin_payout_runs",
)
def payout_runs(principal: AdminOnly, db: Db) -> list[PayoutRun]:
    return admin_service.payout_runs(db)


@router.post(
    "/payout-runs",
    response_model=PayoutRunOut,
    status_code=status.HTTP_201_CREATED,
    operation_id="admin_create_payout_run",
)
def create_payout_run(
    body: PayoutRunIn, principal: AdminOnly, db: Db, request: Request
) -> PayoutRun:
    run = admin_service.create_payout_run(
        db,
        admin=_admin(db, principal),
        payout_ids=body.payout_ids,
        ip=client_ip(request),
    )
    db.commit()
    return run


@router.post(
    "/payout-runs/{run_id}/paid",
    response_model=PayoutRunOut,
    operation_id="admin_mark_payout_run_paid",
)
def mark_run_paid(
    run_id: str, body: PayoutRunPaidIn, principal: AdminOnly, db: Db, request: Request
) -> PayoutRun:
    run = admin_service.mark_run_paid(
        db,
        run_id=run_id,
        admin=_admin(db, principal),
        reference=body.reference,
        ip=client_ip(request),
    )
    db.commit()
    return run


# -------------------------------------------------------------------- shipping


@router.get("/couriers", response_model=list[CourierOut], operation_id="admin_couriers")
def couriers(principal: AdminOnly, db: Db) -> list[Courier]:
    return admin_service.couriers(db)


@router.patch(
    "/couriers/{courier_id}",
    response_model=CourierOut,
    operation_id="admin_update_courier",
)
def update_courier(courier_id: str, body: CourierUpdateIn, principal: AdminOnly, db: Db) -> Courier:
    courier = admin_service.update_courier(
        db,
        courier_id=courier_id,
        admin=_admin(db, principal),
        changes=body.model_dump(exclude_none=True),
    )
    db.commit()
    return courier


@router.post(
    "/couriers/{courier_id}/rates",
    response_model=ShippingRateOut,
    status_code=status.HTTP_201_CREATED,
    operation_id="admin_add_shipping_rate",
)
def add_rate(courier_id: str, body: ShippingRateIn, principal: AdminOnly, db: Db) -> ShippingRate:
    rate = admin_service.add_rate(
        db, courier_id=courier_id, admin=_admin(db, principal), values=body.model_dump()
    )
    db.commit()
    return rate


@router.patch(
    "/shipping-rates/{rate_id}",
    response_model=ShippingRateOut,
    operation_id="admin_update_shipping_rate",
)
def update_rate(
    rate_id: str, body: ShippingRateUpdateIn, principal: AdminOnly, db: Db
) -> ShippingRate:
    rate = admin_service.update_rate(
        db,
        rate_id=rate_id,
        admin=_admin(db, principal),
        changes=body.model_dump(exclude_none=True),
    )
    db.commit()
    return rate


# ---------------------------------------------------------- resale benchmarks


class ResaleBenchmarkIn(BaseModel):
    category_id: str | None = None
    city: str | None = Field(default=None, max_length=80)
    low_percent: float = Field(gt=0, le=100)
    typical_percent: float = Field(gt=0, le=100)
    high_percent: float = Field(gt=0, le=100)
    note: str = Field(default="", max_length=300)


class ResaleBenchmarkOut(ResaleBenchmarkIn):
    model_config = ConfigDict(from_attributes=True)

    id: str


@router.get(
    "/resale-benchmarks",
    response_model=list[ResaleBenchmarkOut],
    operation_id="admin_resale_benchmarks",
)
def resale_benchmarks(principal: AdminOnly, db: Db) -> list[ResaleBenchmarkOut]:
    """The resale assumptions the profit helper shows buyers."""
    return [ResaleBenchmarkOut.model_validate(r) for r in profit_service.list_benchmarks(db)]


@router.put(
    "/resale-benchmarks",
    response_model=ResaleBenchmarkOut,
    operation_id="admin_save_resale_benchmark",
)
def save_resale_benchmark(
    body: ResaleBenchmarkIn, principal: AdminOnly, db: Db
) -> ResaleBenchmarkOut:
    """Create or replace the benchmark for one category and city."""
    row = profit_service.save_benchmark(db, admin=_admin(db, principal), **body.model_dump())
    db.commit()
    return ResaleBenchmarkOut.model_validate(row)


# ----------------------------------------------------------------------- audit


@router.get("/audit", response_model=list[AuditEntryOut], operation_id="admin_audit_log")
def audit_log(
    principal: AdminOnly,
    db: Db,
    action: Annotated[str | None, Query(max_length=80)] = None,
    entity_type: Annotated[str | None, Query(max_length=40)] = None,
    entity_id: Annotated[str | None, Query(max_length=36)] = None,
    brand_id: Annotated[str | None, Query(max_length=36)] = None,
    actor_user_id: Annotated[str | None, Query(max_length=36)] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[AuditLog]:
    return admin_service.audit_entries(
        db,
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        brand_id=brand_id,
        actor_user_id=actor_user_id,
        limit=limit,
        offset=offset,
    )
