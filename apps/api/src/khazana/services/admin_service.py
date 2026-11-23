"""The operations behind the admin panel.

Admins make the decisions here. The risk score orders the moderation list and
is shown beside each listing, and it decides nothing.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, selectinload

from ..ai.features import risk_scoring
from ..ai.gateway import limits
from ..core.errors import Conflict, NotFound, ValidationFailed
from ..models import (
    AuditLog,
    Brand,
    Courier,
    Dispute,
    Lot,
    Order,
    Payment,
    Payout,
    PayoutRun,
    ResellerProfile,
    ShippingRate,
    User,
)
from ..models.base import utcnow
from ..models.enums import (
    DisputeStatus,
    LotStatus,
    OrderStatus,
    PaymentMethod,
    PaymentStatus,
    PayoutStatus,
    VerificationStatus,
)
from . import approval_service, audit_service, payment_service

MIN_REJECTION_NOTE = 10


@dataclass(slots=True)
class ModerationItem:
    lot: Lot
    risk_score: int
    risk_band: str
    findings: list[str] = field(default_factory=list)


def overview(db: Session) -> dict[str, Any]:
    def count(model: Any, *conditions: Any) -> int:
        return int(db.scalar(select(func.count()).select_from(model).where(*conditions)) or 0)

    order_rows = db.execute(select(Order.status, func.count()).group_by(Order.status)).all()
    due = db.scalar(
        select(func.coalesce(func.sum(Payout.amount_pkr), 0)).where(
            Payout.status == PayoutStatus.PENDING, Payout.scheduled_for <= utcnow()
        )
    )
    return {
        "brands_awaiting_review": count(Brand, Brand.status == VerificationStatus.PENDING),
        "resellers_awaiting_review": count(
            ResellerProfile, ResellerProfile.status == VerificationStatus.PENDING
        ),
        "listings_awaiting_approval": count(
            Lot, Lot.status == LotStatus.PENDING_APPROVAL, Lot.deleted_at.is_(None)
        ),
        "live_listings": count(Lot, Lot.status == LotStatus.LIVE, Lot.deleted_at.is_(None)),
        "open_disputes": count(
            Dispute, Dispute.status.in_([DisputeStatus.OPEN, DisputeStatus.UNDER_REVIEW])
        ),
        "bank_transfers_to_confirm": count(
            Payment,
            Payment.method == PaymentMethod.BANK_TRANSFER,
            Payment.status == PaymentStatus.PENDING,
            Payment.provider_reference.is_not(None),
        ),
        "held_funds_pkr": payment_service.held_total(db),
        "payouts_due_pkr": int(due or 0),
        "ai_spend_today_usd": float(limits.spend_today(db)),
        "orders_by_status": {OrderStatus(status).value: total for status, total in order_rows},
    }


# ---------------------------------------------------------------- verification


def resellers_for_review(
    db: Session, *, status: VerificationStatus = VerificationStatus.PENDING, limit: int = 100
) -> list[ResellerProfile]:
    return list(
        db.scalars(
            select(ResellerProfile)
            .where(ResellerProfile.status == status, ResellerProfile.deleted_at.is_(None))
            .options(selectinload(ResellerProfile.user))
            .order_by(ResellerProfile.created_at)
            .limit(limit)
        ).all()
    )


def review_reseller(
    db: Session,
    *,
    profile_id: str,
    admin: User,
    approve: bool,
    note: str | None,
    ip: str | None = None,
) -> ResellerProfile:
    profile = db.get(ResellerProfile, profile_id)
    if profile is None:
        raise NotFound("That reseller does not exist.")
    cleaned = (note or "").strip()
    if not approve and len(cleaned) < MIN_REJECTION_NOTE:
        raise ValidationFailed("Say what the business needs to fix.")

    before = {"status": VerificationStatus(profile.status).value}
    profile.status = VerificationStatus.VERIFIED if approve else VerificationStatus.REJECTED
    profile.reviewed_by_user_id = admin.id
    profile.reviewed_at = utcnow()
    profile.review_note = cleaned[:500] or None
    db.flush()
    audit_service.record(
        db,
        action="reseller.verified" if approve else "reseller.rejected",
        entity_type="reseller_profile",
        entity_id=profile.id,
        actor_user_id=admin.id,
        actor_role=admin.role,
        before=before,
        after={"status": VerificationStatus(profile.status).value},
        note=cleaned or None,
        ip=ip,
    )
    return profile


# ------------------------------------------------------------------ moderation


def moderation_list(
    db: Session,
    *,
    status: LotStatus | None = None,
    search: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[ModerationItem]:
    statement = (
        select(Lot)
        .where(Lot.deleted_at.is_(None))
        .options(
            selectinload(Lot.manifest_lines),
            selectinload(Lot.photos),
            selectinload(Lot.defects),
        )
    )
    if status is not None:
        statement = statement.where(Lot.status == status)
    if search:
        pattern = f"%{search.strip()}%"
        statement = statement.where(or_(Lot.title.ilike(pattern), Lot.lot_code.ilike(pattern)))

    lots = db.scalars(statement.order_by(Lot.updated_at.desc()).limit(limit).offset(offset)).all()
    items: list[ModerationItem] = []
    for lot in lots:
        facts = risk_scoring.compute_facts(db, lot)
        findings, score = risk_scoring.computed_findings(facts, lot)
        items.append(
            ModerationItem(
                lot=lot,
                risk_score=score,
                risk_band=approval_service.risk_band(score),
                findings=[finding.detail for finding in findings],
            )
        )
    items.sort(key=lambda item: -item.risk_score)
    return items


def take_down(
    db: Session,
    *,
    lot: Lot,
    admin: User,
    withdraw: bool,
    note: str,
    ip: str | None = None,
) -> Lot:
    cleaned = note.strip()
    if len(cleaned) < MIN_REJECTION_NOTE:
        raise ValidationFailed("Say why this listing is being taken down.")
    if withdraw:
        return approval_service.withdraw(db, lot=lot, actor=admin, note=cleaned, ip=ip)
    return approval_service.pause(db, lot=lot, actor=admin, note=cleaned, ip=ip)


# -------------------------------------------------------------------- disputes


def disputes(db: Session, *, status: DisputeStatus | None, limit: int = 100) -> list[Dispute]:
    statement = select(Dispute).order_by(Dispute.created_at)
    if status is not None:
        statement = statement.where(Dispute.status == status)
    return list(db.scalars(statement.limit(limit)).all())


def get_dispute(db: Session, dispute_id: str) -> Dispute:
    dispute = db.get(Dispute, dispute_id)
    if dispute is None:
        raise NotFound("That dispute does not exist.")
    return dispute


def start_dispute_review(db: Session, *, dispute: Dispute, admin: User) -> Dispute:
    if DisputeStatus(dispute.status) != DisputeStatus.OPEN:
        raise Conflict("Only an open dispute can be taken for review.")
    dispute.status = DisputeStatus.UNDER_REVIEW
    db.flush()
    audit_service.record(
        db,
        action="dispute.under_review",
        entity_type="dispute",
        entity_id=dispute.id,
        brand_id=dispute.brand_id,
        actor_user_id=admin.id,
        actor_role=admin.role,
    )
    return dispute


# --------------------------------------------------------------------- payouts


def payouts(
    db: Session,
    *,
    status: PayoutStatus | None = None,
    brand_ids: list[str] | None = None,
    limit: int = 100,
) -> list[Payout]:
    statement = select(Payout).order_by(Payout.scheduled_for)
    if status is not None:
        statement = statement.where(Payout.status == status)
    if brand_ids is not None:
        statement = statement.where(Payout.brand_id.in_(brand_ids))
    return list(db.scalars(statement.limit(limit)).all())


def create_payout_run(
    db: Session,
    *,
    admin: User,
    payout_ids: list[str] | None = None,
    ip: str | None = None,
) -> PayoutRun:
    """Gather payouts that are due, for an admin to send."""
    statement = (
        select(Payout)
        .join(Order, Order.id == Payout.order_id)
        .where(
            Payout.status == PayoutStatus.PENDING,
            Payout.scheduled_for <= utcnow(),
            Order.status == OrderStatus.CONFIRMED,
        )
        .with_for_update(of=Payout)
    )
    if payout_ids is not None:
        statement = statement.where(Payout.id.in_(payout_ids))
    due = list(db.scalars(statement).all())
    if not due:
        raise Conflict("No payouts are due.")
    if payout_ids is not None and len(due) != len(set(payout_ids)):
        raise Conflict("One of those payouts is not due yet.")

    run = PayoutRun(
        created_by_user_id=admin.id,
        status=PayoutStatus.SCHEDULED,
        payout_count=len(due),
        total_pkr=sum(payout.amount_pkr for payout in due),
    )
    db.add(run)
    db.flush()
    for payout in due:
        payout.status = PayoutStatus.SCHEDULED
        payout.run_id = run.id
        payout.approved_by_user_id = admin.id
    db.flush()
    audit_service.record(
        db,
        action="payout_run.created",
        entity_type="payout_run",
        entity_id=run.id,
        actor_user_id=admin.id,
        actor_role=admin.role,
        after={"payouts": run.payout_count, "total_pkr": run.total_pkr},
        ip=ip,
    )
    return run


def mark_run_paid(
    db: Session, *, run_id: str, admin: User, reference: str, ip: str | None = None
) -> PayoutRun:
    """Record that the bank transfers in this run have been sent."""
    run = db.get(PayoutRun, run_id)
    if run is None:
        raise NotFound("That payout run does not exist.")
    if PayoutStatus(run.status) != PayoutStatus.SCHEDULED:
        raise Conflict("This payout run has already been completed.")
    cleaned = reference.strip()
    if len(cleaned) < 3:
        raise ValidationFailed("Enter the bank batch reference.")

    now = utcnow()
    run.status = PayoutStatus.PAID
    run.reference = cleaned[:120]
    run.paid_at = now
    for payout in run.payouts:
        payout.status = PayoutStatus.PAID
        payout.paid_at = now
        payout.reference = cleaned[:120]
    db.flush()
    audit_service.record(
        db,
        action="payout_run.paid",
        entity_type="payout_run",
        entity_id=run.id,
        actor_user_id=admin.id,
        actor_role=admin.role,
        after={"reference": run.reference, "total_pkr": run.total_pkr},
        ip=ip,
    )
    return run


def payout_runs(db: Session, *, limit: int = 50) -> list[PayoutRun]:
    return list(
        db.scalars(select(PayoutRun).order_by(PayoutRun.created_at.desc()).limit(limit)).all()
    )


# -------------------------------------------------------------------- shipping


def couriers(db: Session) -> list[Courier]:
    return list(
        db.scalars(
            select(Courier).options(selectinload(Courier.rates)).order_by(Courier.code)
        ).all()
    )


def update_courier(
    db: Session, *, courier_id: str, admin: User, changes: dict[str, bool]
) -> Courier:
    courier = db.get(Courier, courier_id)
    if courier is None:
        raise NotFound("That courier does not exist.")
    if changes.get("is_default"):
        for other in couriers(db):
            other.is_default = False
    for name, value in changes.items():
        setattr(courier, name, value)
    if courier.is_default and not courier.is_active:
        raise ValidationFailed("The default courier has to be active.")
    db.flush()
    audit_service.record(
        db,
        action="courier.updated",
        entity_type="courier",
        entity_id=courier.id,
        actor_user_id=admin.id,
        actor_role=admin.role,
        after=dict(changes),
    )
    return courier


def add_rate(db: Session, *, courier_id: str, admin: User, values: dict[str, Any]) -> ShippingRate:
    courier = db.get(Courier, courier_id)
    if courier is None:
        raise NotFound("That courier does not exist.")
    rate = ShippingRate(courier_id=courier.id, **values)
    db.add(rate)
    db.flush()
    _audit_rate(db, rate, admin, "shipping_rate.created", values)
    return rate


def update_rate(db: Session, *, rate_id: str, admin: User, changes: dict[str, Any]) -> ShippingRate:
    rate = db.get(ShippingRate, rate_id)
    if rate is None:
        raise NotFound("That rate does not exist.")
    for name, value in changes.items():
        setattr(rate, name, value)
    db.flush()
    _audit_rate(db, rate, admin, "shipping_rate.updated", changes)
    return rate


def _audit_rate(
    db: Session, rate: ShippingRate, admin: User, action: str, values: dict[str, Any]
) -> None:
    audit_service.record(
        db,
        action=action,
        entity_type="shipping_rate",
        entity_id=rate.id,
        actor_user_id=admin.id,
        actor_role=admin.role,
        after=dict(values),
    )


# ----------------------------------------------------------------------- audit


def audit_entries(
    db: Session,
    *,
    action: str | None = None,
    entity_type: str | None = None,
    entity_id: str | None = None,
    brand_id: str | None = None,
    actor_user_id: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[AuditLog]:
    statement = select(AuditLog)
    if action:
        statement = statement.where(AuditLog.action.ilike(f"{action}%"))
    if entity_type:
        statement = statement.where(AuditLog.entity_type == entity_type)
    if entity_id:
        statement = statement.where(AuditLog.entity_id == entity_id)
    if brand_id:
        statement = statement.where(AuditLog.brand_id == brand_id)
    if actor_user_id:
        statement = statement.where(AuditLog.actor_user_id == actor_user_id)
    return list(
        db.scalars(statement.order_by(AuditLog.created_at.desc()).limit(limit).offset(offset)).all()
    )
