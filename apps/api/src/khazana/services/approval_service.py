"""The brand approval gate, brand protection, and who may see a listing.

This is week 22, and it exists because of the single promise that makes a
surplus marketplace sellable to a brand at all: nothing with your name on it
reaches a buyer until you have said so, and you can prove afterwards what you
agreed to.

Four mechanisms, in the order a brand meets them:

1. **The approval gate.** A lot reaches a buyer only through `approve`, which
   writes an append only `ListingApproval` row holding a snapshot of the exact
   listing as approved. The table has a database trigger blocking UPDATE and
   DELETE, so the record cannot be tidied up later. `require_brand_approval`
   is pinned true in the schema and absent from the editable policy fields, so
   there is no configuration that turns this off.

2. **Protection level.** PUBLIC shows the brand name. UNBRANDED shows the
   listing with a generic label instead. PRIVATE hides it from anyone who is
   not a verified reseller. A brand that will not sell surplus under its own
   name can still sell it, which is the commercial reason the platform has
   inventory at all.

3. **Region lock.** A brand excludes the cities where it has retail presence,
   per brand by default and per lot when a single lot needs different rules.
   This is the objection a brand raises first: that discounted stock will show
   up next to its own shop.

4. **Withdraw.** One call pulls a listing out of the catalogue at any point.
   Not a delete: the lot and its approval history stay, because the brand may
   relist next season and the record of what was sold has to survive.

The visibility rules are in one function, `visibility_filter`, used by every
buyer facing query. A second copy of these conditions written inline in a
search endpoint is how a private lot ends up in a public result, so there is
deliberately only one.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import ColumnElement, Select, and_, func, or_, select
from sqlalchemy.orm import Session, selectinload

from ..ai.features import risk_scoring
from ..core.errors import Conflict, NotFound, ValidationFailed
from ..models import (
    Brand,
    BrandExcludedCity,
    ListingApproval,
    Lot,
    LotExcludedCity,
    User,
)
from ..models.enums import (
    ApprovalAction,
    LotStatus,
    UserRole,
    VerificationStatus,
    Visibility,
)
from . import audit_service, catalog_service

# The listing payload captured at approval. Chosen so that the snapshot
# answers the only question that matters in a dispute: was the buyer shown
# what the brand agreed to? Photographs are recorded as keys and a count
# rather than inline, because the bytes are immutable once stored.
APPROVAL_SNAPSHOT_FIELDS = (
    "lot_code",
    "title",
    "description",
    "category_id",
    "condition_grade",
    "total_pieces",
    "retail_price_per_piece_pkr",
    "lot_price_pkr",
    "min_order_pieces",
    "stock_city",
    "expiry_date",
    "available_until",
    "visibility",
)

# A rejection has to say why. "Rejected" with no reason is an endpoint that
# generates support tickets.
MIN_REJECTION_NOTE = 10


@dataclass(slots=True)
class QueueItem:
    """One lot awaiting a decision, with everything needed to decide."""

    lot: Lot
    risk_score: int = 0
    risk_band: str = "unknown"
    findings: list[str] = field(default_factory=list)


@dataclass(slots=True)
class Presentation:
    """How one lot should be shown to one viewer.

    Built here rather than in the router, because the brand name is the thing
    being protected and deciding whether to show it is not a formatting
    concern.
    """

    lot: Lot
    brand_name: str
    brand_is_hidden: bool
    show_contact: bool


# ----------------------------------------------------------- the approval gate


def approve(
    db: Session,
    *,
    lot: Lot,
    actor: User,
    visibility: Visibility | None = None,
    note: str | None = None,
    publish: bool = True,
    ip: str | None = None,
) -> Lot:
    """Approve a submitted lot, and by default put it live.

    `publish` exists because approving and publishing are different decisions:
    a brand may approve a lot now and release it when the season turns. The
    default is true because for most lots they are the same moment and a lot
    sitting approved but invisible is a listing nobody is selling.

    The brand must be verified. A suspended or pending brand cannot push stock
    live, and checking here rather than only at registration means a brand
    suspended after submitting cannot have a queued lot slip out.
    """
    if LotStatus(lot.status) != LotStatus.PENDING_APPROVAL:
        raise Conflict(
            f"Only a lot awaiting approval can be approved. This one is "
            f"{LotStatus(lot.status).value}."
        )

    brand = _require_brand(db, lot.brand_id)
    if VerificationStatus(brand.status) != VerificationStatus.VERIFIED:
        raise Conflict(
            f"{brand.name} is {VerificationStatus(brand.status).value}, so its listings "
            f"cannot go live. Complete verification first."
        )

    # Re-check readiness at the gate. The lot passed these tests when it was
    # submitted, but a photograph may have been removed since, and the brand is
    # about to put its name on whatever is here now.
    state = catalog_service.readiness(db, lot)
    if not state.ready:
        raise ValidationFailed(
            "This lot is no longer ready to approve. " + " ".join(state.blockers)
        )

    if visibility is not None:
        lot.visibility = visibility

    lot.approved_at = datetime.now(UTC)
    lot.approved_by_user_id = actor.id
    db.flush()

    catalog_service.transition(db, lot=lot, to=LotStatus.APPROVED, actor=actor, note=note, ip=ip)
    _record_decision(db, lot=lot, actor=actor, action=ApprovalAction.APPROVED, note=note, ip=ip)

    if publish:
        catalog_service.transition(db, lot=lot, to=LotStatus.LIVE, actor=actor, ip=ip)
    return lot


def reject(db: Session, *, lot: Lot, actor: User, note: str, ip: str | None = None) -> Lot:
    """Send a submitted lot back to draft with a reason."""
    if LotStatus(lot.status) != LotStatus.PENDING_APPROVAL:
        raise Conflict(
            f"Only a lot awaiting approval can be rejected. This one is "
            f"{LotStatus(lot.status).value}."
        )
    reason = note.strip()
    if len(reason) < MIN_REJECTION_NOTE:
        raise ValidationFailed(
            "Say what needs fixing. Whoever prepared this listing has to act on the "
            "rejection, and a one word reason means another round trip."
        )

    catalog_service.transition(db, lot=lot, to=LotStatus.DRAFT, actor=actor, note=reason, ip=ip)
    _record_decision(db, lot=lot, actor=actor, action=ApprovalAction.REJECTED, note=reason, ip=ip)
    return lot


def publish(db: Session, *, lot: Lot, actor: User, ip: str | None = None) -> Lot:
    """Put an approved lot into the catalogue."""
    if lot.approved_at is None:
        raise Conflict("This lot has never been approved, so it cannot go live.")
    return catalog_service.transition(db, lot=lot, to=LotStatus.LIVE, actor=actor, ip=ip)


def pause(
    db: Session, *, lot: Lot, actor: User, note: str | None = None, ip: str | None = None
) -> Lot:
    """Take a live lot out of the catalogue without losing its approval.

    The approval survives, so resuming is one call and does not need a second
    review. This is the right tool for stock that is temporarily unavailable,
    and `withdraw` is the right one for stock that is gone.
    """
    lot = catalog_service.transition(
        db, lot=lot, to=LotStatus.PAUSED, actor=actor, note=note, ip=ip
    )
    _record_decision(db, lot=lot, actor=actor, action=ApprovalAction.PAUSED, note=note, ip=ip)
    return lot


def resume(db: Session, *, lot: Lot, actor: User, ip: str | None = None) -> Lot:
    """Put a paused lot back into the catalogue.

    Guarded against the case the CHECK constraint would otherwise catch: a lot
    whose approval was reset while it was paused has to go round again.
    """
    if lot.approved_at is None:
        raise Conflict(
            "This lot lost its approval while it was paused, so it needs to be "
            "approved again before it can go live."
        )
    lot = catalog_service.transition(db, lot=lot, to=LotStatus.LIVE, actor=actor, ip=ip)
    _record_decision(db, lot=lot, actor=actor, action=ApprovalAction.RESUMED, ip=ip)
    return lot


def withdraw(
    db: Session, *, lot: Lot, actor: User, note: str | None = None, ip: str | None = None
) -> Lot:
    """Pull a lot out of the catalogue for good.

    Not a delete. The lot, its manifest and its approval history all stay, so
    the brand can relist next season and so any order already placed against
    it still has something to point at.
    """
    lot = catalog_service.transition(
        db, lot=lot, to=LotStatus.WITHDRAWN, actor=actor, note=note, ip=ip
    )
    # The approval no longer applies. Without this a withdrawn lot could be
    # taken back to draft and relisted on an approval given for the old price.
    lot.approved_at = None
    lot.approved_by_user_id = None
    db.flush()

    _record_decision(db, lot=lot, actor=actor, action=ApprovalAction.WITHDRAWN, note=note, ip=ip)
    return lot


def submit(db: Session, *, lot: Lot, actor: User, ip: str | None = None) -> Lot:
    """Submit for approval, recording it in the approval trail.

    `catalog_service.submit_for_approval` owns the readiness checks and the
    status change. This wrapper adds the `ListingApproval` row, so the trail
    shows the submission as well as the decision on it.
    """
    lot = catalog_service.submit_for_approval(db, lot=lot, actor=actor, ip=ip)
    _record_decision(db, lot=lot, actor=actor, action=ApprovalAction.SUBMITTED, ip=ip)
    return lot


# ------------------------------------------------------------ brand protection


def set_visibility(
    db: Session,
    *,
    lot: Lot,
    actor: User,
    visibility: Visibility,
    ip: str | None = None,
) -> Lot:
    """Change the protection level on one lot.

    Allowed while live, and deliberately so. Tightening protection is the
    action a brand takes in a hurry, usually because a retail partner
    complained, and making them pause the lot first would mean the listing
    stays public while they work out how.

    Going to UNBRANDED needs a label on the brand, because the alternative is
    showing a listing labelled "Unknown", which reads as a scam.
    """
    current = Visibility(lot.visibility)
    if current == visibility:
        return lot

    if visibility == Visibility.UNBRANDED:
        brand = _require_brand(db, lot.brand_id)
        if not brand.unbranded_label:
            raise ValidationFailed(
                "Set an unbranded label on the brand first. Buyers need something to "
                "call this stock, and an unlabelled listing looks like a scam."
            )

    before = {"visibility": current.value}
    lot.visibility = visibility
    db.flush()

    audit_service.record(
        db,
        action="lot.visibility_changed",
        entity_type="lot",
        entity_id=lot.id,
        brand_id=lot.brand_id,
        actor_user_id=actor.id,
        actor_role=actor.role,
        before=before,
        after={"visibility": visibility.value},
        ip=ip,
    )
    return lot


def set_region_lock(
    db: Session,
    *,
    lot: Lot,
    actor: User,
    cities: list[str],
    ip: str | None = None,
) -> list[str]:
    """Replace this lot's excluded cities, overriding the brand default.

    An empty list means this lot is sold everywhere, which is different from
    having no override: there is no way to express "inherit again" here, and
    that is intentional. An explicit per lot list that happens to be empty is
    a decision, and a brand that wants the default back can say so by matching
    it.
    """
    cleaned: list[str] = []
    seen: set[str] = set()
    for raw in cities:
        city = str(raw).strip()
        if not city:
            continue
        if len(city) > 80:
            raise ValidationFailed(f"{city[:30]}... is not a city name.")
        key = city.casefold()
        if key in seen:
            continue
        seen.add(key)
        cleaned.append(city)

    if lot.stock_city.casefold() in seen:
        raise ValidationFailed(
            f"The stock is held in {lot.stock_city}, so it cannot be excluded from "
            f"{lot.stock_city}."
        )

    before = sorted(entry.city for entry in lot.excluded_cities)
    lot.excluded_cities.clear()
    db.flush()
    for city in cleaned:
        lot.excluded_cities.append(LotExcludedCity(brand_id=lot.brand_id, city=city))
    db.flush()

    audit_service.record(
        db,
        action="lot.region_lock_set",
        entity_type="lot",
        entity_id=lot.id,
        brand_id=lot.brand_id,
        actor_user_id=actor.id,
        actor_role=actor.role,
        before={"cities": before},
        after={"cities": cleaned},
        ip=ip,
    )
    return cleaned


def excluded_cities_for(db: Session, lot: Lot) -> list[str]:
    """The cities this lot is not sold in: its own list, or the brand default.

    Per lot overrides entirely rather than adding to the brand list. A brand
    that excludes Lahore by default but runs a clearance lot specifically for
    Lahore needs the override to win, and a union would make that impossible
    to express.
    """
    own = [entry.city for entry in lot.excluded_cities]
    if own:
        return sorted(own)
    brand = db.get(Brand, lot.brand_id)
    if brand is None:
        return []
    return sorted(entry.city for entry in brand.default_excluded_cities)


# ------------------------------------------------------------------ visibility


def visibility_filter(
    *, role: UserRole | None, reseller_is_verified: bool, city: str | None
) -> ColumnElement[bool]:
    """The one definition of what a buyer may see.

    Every buyer facing query applies this. Writing these conditions inline in
    a search endpoint is how a private lot ends up in a public result, so this
    is the only copy.

    Note what is absent: no brand identifier, no ownership. This answers "may
    this viewer see this listing", not "does this viewer own it". Ownership is
    `core.tenancy`, and conflating the two is how a brand ends up unable to see
    its own draft.
    """
    live = and_(
        Lot.deleted_at.is_(None),
        Lot.status == LotStatus.LIVE,
        # Belt and braces against the CHECK constraint. A live lot without an
        # approval should be impossible; if one exists, it stays hidden.
        Lot.approved_at.is_not(None),
    )

    if role == UserRole.ADMIN:
        return and_(Lot.deleted_at.is_(None))

    # A private lot is for verified resellers only. Anyone else, including an
    # unauthenticated visitor and an unverified reseller, sees public and
    # unbranded listings.
    if reseller_is_verified:
        allowed: ColumnElement[bool] = Lot.visibility.in_(
            [Visibility.PUBLIC, Visibility.UNBRANDED, Visibility.PRIVATE]
        )
    else:
        allowed = Lot.visibility.in_([Visibility.PUBLIC, Visibility.UNBRANDED])

    conditions = [live, allowed]

    if city:
        # The region lock. A lot is hidden from a city that appears on its own
        # exclusion list, or on its brand's default list when the lot has no
        # list of its own. The correlated NOT EXISTS pair expresses the
        # override: the brand default only applies when no per lot row exists.
        own_exclusion = (
            select(LotExcludedCity.id)
            .where(
                LotExcludedCity.lot_id == Lot.id,
                func.lower(LotExcludedCity.city) == city.casefold(),
            )
            .exists()
        )
        has_own_list = select(LotExcludedCity.id).where(LotExcludedCity.lot_id == Lot.id).exists()
        # BrandExcludedCity, not LotExcludedCity. Written with the wrong model
        # first, which silently disabled the brand default lock and produced a
        # cartesian product across three tables. The visibility tests caught
        # it; the SQLAlchemy cartesian product warning named it.
        brand_exclusion = (
            select(BrandExcludedCity.id)
            .where(
                BrandExcludedCity.brand_id == Lot.brand_id,
                func.lower(BrandExcludedCity.city) == city.casefold(),
            )
            .exists()
        )
        conditions.append(
            and_(
                ~own_exclusion,
                or_(has_own_list, ~brand_exclusion),
            )
        )

    return and_(*conditions)


def browse(
    db: Session,
    *,
    role: UserRole | None,
    reseller_is_verified: bool,
    city: str | None = None,
    category_id: str | None = None,
    limit: int = 24,
    offset: int = 0,
) -> tuple[list[Lot], int]:
    """The buyer facing catalogue.

    A thin wrapper now. Filters, sorting and search are M4 in weeks 23 and 24,
    and they will extend this rather than write their own visibility rules.
    """
    statement: Select[Any] = select(Lot).where(
        visibility_filter(role=role, reseller_is_verified=reseller_is_verified, city=city)
    )
    if category_id:
        statement = statement.where(Lot.category_id == category_id)

    total = (
        db.scalar(
            select(func.count())
            .select_from(Lot)
            .where(
                visibility_filter(role=role, reseller_is_verified=reseller_is_verified, city=city)
            )
            if not category_id
            else select(func.count())
            .select_from(Lot)
            .where(
                visibility_filter(role=role, reseller_is_verified=reseller_is_verified, city=city),
                Lot.category_id == category_id,
            )
        )
        or 0
    )

    rows = list(
        db.scalars(
            statement.options(selectinload(Lot.photos), selectinload(Lot.manifest_lines))
            .order_by(Lot.approved_at.desc())
            .limit(min(limit, 100))
            .offset(max(offset, 0))
        ).all()
    )
    return rows, int(total)


def present(db: Session, lot: Lot, *, viewer_role: UserRole | None) -> Presentation:
    """Decide what name this viewer sees on this lot.

    The brand's own staff and an admin always see the real name: hiding it
    from the owner would be a bug dressed as a feature. For everyone else an
    unbranded lot shows the label instead, and that is the whole of the
    unbranded promise.
    """
    brand = _require_brand(db, lot.brand_id)
    privileged = viewer_role in (UserRole.ADMIN, UserRole.BRAND)

    if Visibility(lot.visibility) == Visibility.UNBRANDED and not privileged:
        return Presentation(
            lot=lot,
            brand_name=brand.unbranded_label or "Unbranded surplus",
            brand_is_hidden=True,
            show_contact=False,
        )
    return Presentation(
        lot=lot,
        brand_name=brand.name,
        brand_is_hidden=False,
        show_contact=privileged,
    )


# --------------------------------------------------------------- review queues


def pending_queue(db: Session, *, brand_ids: list[str] | None, limit: int = 50) -> list[QueueItem]:
    """Lots awaiting a decision, riskiest first.

    The Phase 2 risk score orders the queue; it does not decide anything. A
    high score moves a lot up the list so a person looks at it sooner, which
    is the only authority `docs/ai-architecture.md` section 2 gives it.

    Scoring runs over the computed findings only, which are arithmetic over
    the listing and cost nothing. The model backed half of risk scoring is for
    the admin moderation queue in M8, where one call per lot is affordable.
    """
    conditions = [Lot.deleted_at.is_(None), Lot.status == LotStatus.PENDING_APPROVAL]
    if brand_ids is not None:
        if not brand_ids:
            return []
        conditions.append(Lot.brand_id.in_(brand_ids))

    lots = list(
        db.scalars(
            select(Lot)
            .where(*conditions)
            .options(
                selectinload(Lot.manifest_lines),
                selectinload(Lot.photos),
                selectinload(Lot.defects),
            )
            .order_by(Lot.updated_at.asc())
            .limit(min(limit, 200))
        ).all()
    )

    items: list[QueueItem] = []
    for lot in lots:
        facts = risk_scoring.compute_facts(db, lot)
        findings, score = risk_scoring.computed_findings(facts, lot)
        items.append(
            QueueItem(
                lot=lot,
                risk_score=score,
                risk_band=_band(score),
                findings=[finding.detail for finding in findings],
            )
        )

    items.sort(key=lambda item: (-item.risk_score, item.lot.updated_at))
    return items


def approval_trail(db: Session, *, lot_id: str) -> list[ListingApproval]:
    """Every decision ever recorded against a lot, oldest first.

    This is the evidence the brand is promised. The table is append only,
    enforced by a trigger, so what comes back here is what happened.
    """
    return list(
        db.scalars(
            select(ListingApproval)
            .where(ListingApproval.lot_id == lot_id)
            .order_by(ListingApproval.created_at.asc())
        ).all()
    )


# -------------------------------------------------------------------- internals


def _record_decision(
    db: Session,
    *,
    lot: Lot,
    actor: User,
    action: ApprovalAction,
    note: str | None = None,
    ip: str | None = None,
) -> ListingApproval:
    """Append one row to the approval trail.

    Unlike `audit_service.record`, a failure here is not swallowed. The audit
    log is observability and must never break the action it describes; this
    table is the brand protection promise, and an approval that was not
    recorded did not happen.
    """
    snapshot = audit_service.snapshot(lot, APPROVAL_SNAPSHOT_FIELDS)
    snapshot["manifest_pieces"] = lot.manifest_total
    snapshot["manifest_lines"] = len(lot.manifest_lines)
    snapshot["photo_keys"] = [photo.file_key for photo in lot.photos]
    snapshot["defects"] = [
        {"issue": defect.issue, "pieces_affected": defect.pieces_affected} for defect in lot.defects
    ]

    entry = ListingApproval(
        lot_id=lot.id,
        brand_id=lot.brand_id,
        action=action,
        actor_user_id=actor.id,
        actor_role=str(actor.role),
        visibility_at_action=Visibility(lot.visibility),
        note=note[:500] if note else None,
        snapshot=snapshot,
    )
    db.add(entry)
    db.flush()

    audit_service.record(
        db,
        action=f"listing.{action.value}",
        entity_type="lot",
        entity_id=lot.id,
        brand_id=lot.brand_id,
        actor_user_id=actor.id,
        actor_role=actor.role,
        after={"action": action.value, "visibility": str(lot.visibility)},
        note=note,
        ip=ip,
    )
    return entry


def _require_brand(db: Session, brand_id: str) -> Brand:
    brand = db.get(Brand, brand_id)
    if brand is None or brand.is_deleted:
        raise NotFound("That brand does not exist.")
    return brand


def _band(score: int) -> str:
    """Three buckets, because a queue sorted by a number nobody can interpret
    gets ignored. The thresholds are configuration in M8, where the admin
    moderation queue needs to tune them against real listings."""
    if score >= 60:
        return "high"
    if score >= 30:
        return "medium"
    return "low"
