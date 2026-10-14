"""The brand portal.

Registration, verification, documents and policy. This is the first thing a
brand touches, and the verification decision is the first consequential action
in the platform, so everything here is audited.

Two rules carried from the roadmap and enforced in code, not in a comment:

- **Policy is data.** A brand sets its own commission, discount band, payout
  terms and lot minimum. Those are rows, and this module is how they change.
- **One field is not negotiable.** `require_brand_approval` is pinned true by
  a database constraint. A brand may set its own commercial terms but may not
  remove its own protection, because that protection is the reason it is
  willing to list at all.

Verification is a state machine with exactly one path to verified, and only an
admin can move it there. A brand that could verify itself is not verification.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..core.errors import Conflict, Forbidden, NotFound, ValidationFailed
from ..models import (
    Brand,
    BrandExcludedCity,
    BrandMember,
    BrandPolicy,
    Lot,
    Order,
    User,
    VerificationDocument,
)
from ..models.base import utcnow
from ..models.enums import (
    BrandMemberRole,
    DocumentType,
    LotStatus,
    OrderStatus,
    UserRole,
    VerificationStatus,
    Visibility,
)
from ..storage import (
    ALLOWED_DOCUMENT_TYPES,
    StorageError,
    build_key,
    checksum,
    put_object,
    validate_upload,
)
from . import audit_service

logger = logging.getLogger(__name__)

SLUG_PATTERN = re.compile(r"[^a-z0-9]+")

# Documents a brand must supply before an admin can verify it. The NTN and
# proof of incorporation are what make the seller a real registered business,
# which is what lets the platform issue a proper invoice.
REQUIRED_DOCUMENTS: tuple[DocumentType, ...] = (
    DocumentType.NTN,
    DocumentType.INCORPORATION,
)

# Fields captured in an audit snapshot. An explicit list, so adding a column
# never silently starts logging something that should not be logged.
BRAND_AUDIT_FIELDS = (
    "name",
    "legal_name",
    "slug",
    "ntn",
    "city",
    "status",
    "unbranded_label",
    "contact_phone",
    "contact_email",
)
POLICY_AUDIT_FIELDS = (
    "commission_percent",
    "payout_terms_days",
    "min_lot_value_pkr",
    "min_discount_percent",
    "max_discount_percent",
    "default_visibility",
    "require_brand_approval",
    "allow_cod",
    "allow_part_lot_orders",
    "auto_apply_ai_draft",
    "ai_monthly_budget_usd",
)


@dataclass(slots=True)
class BrandDashboard:
    brand: Brand
    policy: BrandPolicy
    status: VerificationStatus
    documents_supplied: list[DocumentType]
    documents_missing: list[DocumentType]
    can_request_verification: bool
    lots_by_status: dict[str, int]
    live_lots: int
    orders_this_month: int
    awaiting_payout_pkr: int

    @property
    def is_verified(self) -> bool:
        return self.status == VerificationStatus.VERIFIED


def slugify(name: str) -> str:
    """A URL safe identifier from a brand name."""
    slug = SLUG_PATTERN.sub("-", name.strip().lower()).strip("-")
    if not slug:
        raise ValidationFailed("That brand name cannot be turned into a web address.")
    return slug[:160]


def register_brand(
    db: Session,
    *,
    owner: User,
    name: str,
    city: str,
    legal_name: str | None = None,
    ntn: str | None = None,
    contact_email: str | None = None,
    ip: str | None = None,
) -> Brand:
    """Create a brand, its policy row and the owner's membership.

    The policy row is created here rather than lazily, because every later
    read assumes it exists. A brand without a policy has no commission rate
    and no discount band, which makes it unpriceable rather than merely
    incomplete.
    """
    name = " ".join(name.split())
    if len(name) < 2:
        raise ValidationFailed("Enter the brand name.")

    slug = slugify(name)
    if db.scalars(select(Brand).where(Brand.slug == slug)).first() is not None:
        raise Conflict(
            f"A brand with the web address {slug!r} already exists. "
            "Choose a slightly different name."
        )

    brand = Brand(
        name=name,
        legal_name=legal_name,
        slug=slug,
        ntn=ntn,
        city=city.strip(),
        status=VerificationStatus.PENDING,
        contact_phone=owner.phone,
        contact_email=contact_email,
    )
    db.add(brand)
    db.flush()

    db.add(BrandPolicy(brand_id=brand.id))
    db.add(BrandMember(brand_id=brand.id, user_id=owner.id, role_in_brand=BrandMemberRole.OWNER))

    # The person registering a brand becomes a brand user. Without this they
    # would register a brand and then be unable to see it.
    if owner.role == UserRole.RESELLER:
        owner.role = UserRole.BRAND

    audit_service.record(
        db,
        action="brand.registered",
        entity_type="brand",
        entity_id=brand.id,
        brand_id=brand.id,
        actor_user_id=owner.id,
        actor_role=owner.role,
        after=audit_service.snapshot(brand, BRAND_AUDIT_FIELDS),
        ip=ip,
    )
    db.flush()
    return brand


def upload_document(
    db: Session,
    *,
    brand_id: str,
    doc_type: DocumentType,
    data: bytes,
    filename: str,
    content_type: str,
    uploaded_by: User,
    ip: str | None = None,
) -> VerificationDocument:
    """Store one verification document.

    The file is validated against its own magic bytes before anything is
    written, and the key is generated rather than taken from the filename.
    """
    brand = _get_brand(db, brand_id)

    if brand.status == VerificationStatus.VERIFIED:
        raise Conflict("This brand is already verified. Contact support to change documents.")

    try:
        validate_upload(data, content_type, allowed=ALLOWED_DOCUMENT_TYPES)
    except StorageError as exc:
        raise ValidationFailed(str(exc)) from exc

    digest = checksum(data)
    existing = db.scalars(
        select(VerificationDocument).where(
            VerificationDocument.brand_id == brand_id,
            VerificationDocument.doc_type == doc_type,
        )
    ).first()

    key = build_key(prefix="verification", brand_id=brand_id, content_type=content_type)
    put_object(key, data, content_type)

    if existing is not None:
        # Replacing a document resets its review. An admin who already looked
        # at the old one has not seen this.
        before = audit_service.snapshot(existing, ("doc_type", "status", "file_key"))
        existing.file_key = key
        existing.original_filename = filename[:255]
        existing.content_type = content_type
        existing.size_bytes = len(data)
        existing.status = VerificationStatus.PENDING
        existing.reviewed_by_user_id = None
        existing.reviewed_at = None
        existing.review_note = None
        document = existing
        db.flush()
        audit_service.record(
            db,
            action="brand.document_replaced",
            entity_type="verification_document",
            entity_id=document.id,
            brand_id=brand_id,
            actor_user_id=uploaded_by.id,
            actor_role=uploaded_by.role,
            before=before,
            after=audit_service.snapshot(document, ("doc_type", "status", "file_key")),
            note=f"checksum {digest[:16]}",
            ip=ip,
        )
    else:
        document = VerificationDocument(
            brand_id=brand_id,
            doc_type=doc_type,
            file_key=key,
            original_filename=filename[:255],
            content_type=content_type,
            size_bytes=len(data),
            status=VerificationStatus.PENDING,
            uploaded_by_user_id=uploaded_by.id,
        )
        db.add(document)
        db.flush()
        audit_service.record(
            db,
            action="brand.document_uploaded",
            entity_type="verification_document",
            entity_id=document.id,
            brand_id=brand_id,
            actor_user_id=uploaded_by.id,
            actor_role=uploaded_by.role,
            after=audit_service.snapshot(document, ("doc_type", "status", "file_key")),
            note=f"checksum {digest[:16]}",
            ip=ip,
        )

    return document


def missing_documents(db: Session, brand_id: str) -> list[DocumentType]:
    supplied = set(
        db.scalars(
            select(VerificationDocument.doc_type).where(VerificationDocument.brand_id == brand_id)
        ).all()
    )
    return [doc for doc in REQUIRED_DOCUMENTS if doc not in supplied]


def request_verification(
    db: Session, *, brand_id: str, requested_by: User, ip: str | None = None
) -> Brand:
    """Move a brand into the admin review queue.

    Refused while documents are missing. Letting an incomplete application
    into the queue wastes the admin's time and teaches brands that the
    requirements are optional.
    """
    brand = _get_brand(db, brand_id)

    if brand.status == VerificationStatus.VERIFIED:
        raise Conflict("This brand is already verified.")
    if brand.status == VerificationStatus.SUSPENDED:
        raise Forbidden("This brand is suspended. Contact support.")

    missing = missing_documents(db, brand_id)
    if missing:
        names = ", ".join(doc.value for doc in missing)
        raise ValidationFailed(f"Upload these documents first: {names}.")

    before = audit_service.snapshot(brand, BRAND_AUDIT_FIELDS)
    brand.status = VerificationStatus.PENDING
    brand.reviewed_by_user_id = None
    brand.reviewed_at = None
    brand.review_note = None
    db.flush()

    audit_service.record(
        db,
        action="brand.verification_requested",
        entity_type="brand",
        entity_id=brand.id,
        brand_id=brand.id,
        actor_user_id=requested_by.id,
        actor_role=requested_by.role,
        before=before,
        after=audit_service.snapshot(brand, BRAND_AUDIT_FIELDS),
        ip=ip,
    )
    return brand


def review_brand(
    db: Session,
    *,
    brand_id: str,
    admin: User,
    approve: bool,
    note: str | None = None,
    ip: str | None = None,
) -> Brand:
    """Approve or reject a brand. Admin only, always audited.

    A rejection requires a reason. A brand told only "rejected" cannot fix
    anything, and will either give up or resubmit the same application.
    """
    if admin.role != UserRole.ADMIN:
        raise Forbidden("Only an admin can verify a brand.")

    brand = _get_brand(db, brand_id)

    if not approve and not (note or "").strip():
        raise ValidationFailed("Give a reason for the rejection so the brand can fix it.")

    if approve and missing_documents(db, brand_id):
        raise ValidationFailed(
            "This brand has not supplied all the required documents, so it cannot be verified yet."
        )

    before = audit_service.snapshot(brand, BRAND_AUDIT_FIELDS)
    brand.status = VerificationStatus.VERIFIED if approve else VerificationStatus.REJECTED
    brand.reviewed_by_user_id = admin.id
    brand.reviewed_at = utcnow()
    brand.review_note = (note or "").strip()[:500] or None

    if approve:
        for document in db.scalars(
            select(VerificationDocument).where(VerificationDocument.brand_id == brand_id)
        ).all():
            document.status = VerificationStatus.VERIFIED
            document.reviewed_by_user_id = admin.id
            document.reviewed_at = utcnow()

    db.flush()

    audit_service.record(
        db,
        action="brand.verified" if approve else "brand.rejected",
        entity_type="brand",
        entity_id=brand.id,
        brand_id=brand.id,
        actor_user_id=admin.id,
        actor_role=admin.role,
        before=before,
        after=audit_service.snapshot(brand, BRAND_AUDIT_FIELDS),
        note=brand.review_note,
        ip=ip,
    )
    return brand


def suspend_brand(
    db: Session, *, brand_id: str, admin: User, reason: str, ip: str | None = None
) -> Brand:
    """Suspend a brand and take its live listings down with it.

    Leaving listings up would let a suspended brand keep taking orders, which
    is the whole reason for suspending it.
    """
    if admin.role != UserRole.ADMIN:
        raise Forbidden("Only an admin can suspend a brand.")
    if not reason.strip():
        raise ValidationFailed("Give a reason for the suspension.")

    brand = _get_brand(db, brand_id)
    before = audit_service.snapshot(brand, BRAND_AUDIT_FIELDS)

    brand.status = VerificationStatus.SUSPENDED
    brand.reviewed_by_user_id = admin.id
    brand.reviewed_at = utcnow()
    brand.review_note = reason.strip()[:500]

    paused = 0
    for lot in db.scalars(
        select(Lot).where(Lot.brand_id == brand_id, Lot.status == LotStatus.LIVE)
    ).all():
        lot.status = LotStatus.PAUSED
        paused += 1

    db.flush()

    audit_service.record(
        db,
        action="brand.suspended",
        entity_type="brand",
        entity_id=brand.id,
        brand_id=brand.id,
        actor_user_id=admin.id,
        actor_role=admin.role,
        before=before,
        after=audit_service.snapshot(brand, BRAND_AUDIT_FIELDS),
        note=f"{reason.strip()[:400]} ({paused} live lots paused)",
        ip=ip,
    )
    return brand


def update_policy(
    db: Session,
    *,
    brand_id: str,
    actor: User,
    changes: dict[str, object],
    ip: str | None = None,
) -> BrandPolicy:
    """Change a brand's commercial terms.

    Policy is data, so this is an ordinary update. Three guards:

    - Only fields a brand is allowed to set can be changed here.
    - The discount band must stay ordered, checked before the database does,
      so the brand gets a sentence rather than a constraint violation.
    - `require_brand_approval` is not in the editable set at all. It is pinned
      true in the schema, and offering it as an editable field would promise
      something the database will refuse.
    """
    policy = db.scalars(select(BrandPolicy).where(BrandPolicy.brand_id == brand_id)).first()
    if policy is None:
        raise NotFound("That brand has no policy row.")

    editable = {
        "commission_percent",
        "payout_terms_days",
        "min_lot_value_pkr",
        "min_discount_percent",
        "max_discount_percent",
        "default_visibility",
        "allow_cod",
        "allow_part_lot_orders",
        "auto_apply_ai_draft",
        "ai_monthly_budget_usd",
    }

    rejected = set(changes) - editable
    if rejected:
        if "require_brand_approval" in rejected:
            raise ValidationFailed(
                "Brand approval cannot be switched off. Every listing needs your "
                "approval before a buyer can see it, and that protection is not "
                "optional."
            )
        raise ValidationFailed(f"These settings cannot be changed here: {sorted(rejected)}.")

    before = audit_service.snapshot(policy, POLICY_AUDIT_FIELDS)

    low = float(changes.get("min_discount_percent", policy.min_discount_percent))  # type: ignore[arg-type]
    high = float(changes.get("max_discount_percent", policy.max_discount_percent))  # type: ignore[arg-type]
    if low >= high:
        raise ValidationFailed(
            f"The minimum discount ({low:.0f} percent) must be below the maximum "
            f"({high:.0f} percent)."
        )

    for field, value in changes.items():
        setattr(policy, field, value)
    db.flush()

    # Refresh before snapshotting, so the audit records the value as stored
    # rather than as typed. Without this a commission set to 15 is captured as
    # the integer 15 while the previous value came back from the database as
    # Decimal("15.00"), and the diff reports a change that did not happen.
    db.refresh(policy)
    after = audit_service.snapshot(policy, POLICY_AUDIT_FIELDS)
    audit_service.record(
        db,
        action="brand.policy_updated",
        entity_type="brand_policy",
        entity_id=policy.id,
        brand_id=brand_id,
        actor_user_id=actor.id,
        actor_role=actor.role,
        before=before,
        after=audit_service.diff(before, after),
        ip=ip,
    )
    return policy


def set_excluded_cities(
    db: Session, *, brand_id: str, cities: list[str], actor: User, ip: str | None = None
) -> list[str]:
    """Replace the brand's default region lock.

    The cities a brand excludes by default, inherited by every new lot. A lot
    can still override its own list.
    """
    _get_brand(db, brand_id)

    cleaned = sorted({city.strip().title() for city in cities if city.strip()})
    before = sorted(
        db.scalars(
            select(BrandExcludedCity.city).where(BrandExcludedCity.brand_id == brand_id)
        ).all()
    )

    for row in db.scalars(
        select(BrandExcludedCity).where(BrandExcludedCity.brand_id == brand_id)
    ).all():
        db.delete(row)
    db.flush()

    for city in cleaned:
        db.add(BrandExcludedCity(brand_id=brand_id, city=city))
    db.flush()

    audit_service.record(
        db,
        action="brand.region_lock_updated",
        entity_type="brand",
        entity_id=brand_id,
        brand_id=brand_id,
        actor_user_id=actor.id,
        actor_role=actor.role,
        before={"excluded_cities": before},
        after={"excluded_cities": cleaned},
        ip=ip,
    )
    return cleaned


def dashboard(db: Session, brand_id: str) -> BrandDashboard:
    """Everything the brand portal home screen needs, in one query set."""
    brand = _get_brand(db, brand_id)
    policy = db.scalars(select(BrandPolicy).where(BrandPolicy.brand_id == brand_id)).first()
    if policy is None:
        raise NotFound("That brand has no policy row.")

    supplied = list(
        db.scalars(
            select(VerificationDocument.doc_type).where(VerificationDocument.brand_id == brand_id)
        ).all()
    )
    missing = missing_documents(db, brand_id)

    counts = dict(
        db.execute(
            select(Lot.status, func.count())
            .where(Lot.brand_id == brand_id, Lot.deleted_at.is_(None))
            .group_by(Lot.status)
        ).all()
    )
    lots_by_status = {
        status.value if hasattr(status, "value") else str(status): count
        for status, count in counts.items()
    }

    since = utcnow().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    orders_this_month = (
        db.scalar(
            select(func.count())
            .select_from(Order)
            .where(Order.brand_id == brand_id, Order.created_at >= since)
        )
        or 0
    )

    awaiting = (
        db.scalar(
            select(func.coalesce(func.sum(Order.brand_payout_pkr), 0)).where(
                Order.brand_id == brand_id,
                Order.status.in_([OrderStatus.PAID, OrderStatus.SHIPPED, OrderStatus.DELIVERED]),
            )
        )
        or 0
    )

    return BrandDashboard(
        brand=brand,
        policy=policy,
        status=brand.status,
        documents_supplied=supplied,
        documents_missing=missing,
        can_request_verification=(
            not missing
            and brand.status in {VerificationStatus.PENDING, VerificationStatus.REJECTED}
        ),
        lots_by_status=lots_by_status,
        live_lots=lots_by_status.get(LotStatus.LIVE.value, 0),
        orders_this_month=int(orders_this_month),
        awaiting_payout_pkr=int(awaiting),
    )


def default_visibility_for(db: Session, brand_id: str) -> Visibility:
    """The protection level a new lot inherits."""
    policy = db.scalars(select(BrandPolicy).where(BrandPolicy.brand_id == brand_id)).first()
    return policy.default_visibility if policy else Visibility.PRIVATE


def _get_brand(db: Session, brand_id: str) -> Brand:
    brand = db.get(Brand, brand_id)
    if brand is None or brand.is_deleted:
        raise NotFound("That brand does not exist.")
    return brand
