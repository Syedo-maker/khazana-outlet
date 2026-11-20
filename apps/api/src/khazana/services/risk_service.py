"""Fraud and counterfeit risk: signals, scores and the review queue.

Each signal is a rule with a weight and a sentence saying what it saw, so a
reviewer reads why a case exists rather than a bare number. Listings also
take the AI risk score where one was recorded; it is one signal among the
others, not a verdict.

What this never does: suspend an account, pause a listing or cancel an order.
It opens cases. A person decides, and the decision, with any action that
person chose, is audited.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..core.errors import Conflict, NotFound, ValidationFailed
from ..models import (
    AiJob,
    AiOutput,
    Brand,
    Dispute,
    Lot,
    Order,
    OtpChallenge,
    ResellerProfile,
    ReviewCase,
    User,
    utcnow,
)
from ..models.enums import (
    AiFeature,
    LotStatus,
    OrderStatus,
    PaymentMethod,
    ReviewStatus,
    UserRole,
    VerificationStatus,
)
from . import audit_service, catalog_service

WINDOW_DAYS = 30
BIG_ORDER_PKR = 500_000
BIG_COD_PKR = 200_000
SHARED_PHONE_ACCOUNTS = 3
ACTIONS = ("none", "suspend_account", "pause_listing")


@dataclass(slots=True)
class Signal:
    code: str
    weight: int
    detail: str


@dataclass(slots=True)
class Assessment:
    subject_type: str
    subject_id: str
    brand_id: str | None
    signals: list[Signal] = field(default_factory=list)

    @property
    def score(self) -> int:
        return min(100, sum(s.weight for s in self.signals))


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=UTC)


def _phone_accounts(db: Session) -> Counter[str]:
    """How many different buyer accounts used each delivery phone."""
    rows = db.execute(select(Order.delivery_phone, Order.buyer_user_id).distinct()).all()
    return Counter(phone for phone, _ in rows)


def assess_account(db: Session, user: User, now: datetime, phones: Counter[str]) -> Assessment:
    result = Assessment("account", user.id, None)
    since = now - timedelta(days=WINDOW_DAYS)
    failed = db.scalar(
        select(func.count())
        .select_from(OtpChallenge)
        .where(
            OtpChallenge.phone == user.phone,
            OtpChallenge.attempts >= 3,
            OtpChallenge.consumed_at.is_(None),
            OtpChallenge.created_at >= now - timedelta(days=1),
        )
    )
    if failed and failed >= 3:
        result.signals.append(
            Signal("failed_logins", 20, f"{failed} sign in codes failed in the last day.")
        )
    orders = list(db.scalars(select(Order).where(Order.buyer_user_id == user.id)))
    refused = [
        o
        for o in orders
        if o.payment_method == PaymentMethod.COD and o.status == OrderStatus.CANCELLED
    ]
    if len(refused) >= 2:
        result.signals.append(
            Signal("cod_refusals", 30, f"{len(refused)} cash on delivery orders were cancelled.")
        )
    shared = {o.delivery_phone for o in orders if phones[o.delivery_phone] >= SHARED_PHONE_ACCOUNTS}
    if shared:
        result.signals.append(
            Signal(
                "shared_phone",
                25,
                f"A delivery number on this account is used by {SHARED_PHONE_ACCOUNTS} or more "
                "accounts.",
            )
        )
    age = now - _aware(user.created_at)
    big = [o for o in orders if o.total_pkr >= BIG_ORDER_PKR]
    if age < timedelta(days=7) and big:
        result.signals.append(
            Signal(
                "new_account_big_order",
                25,
                f"An order of Rs {big[0].total_pkr:,} from an account {age.days} days old.",
            )
        )
    disputes = db.scalar(
        select(func.count())
        .select_from(Dispute)
        .where(Dispute.raised_by_user_id == user.id, Dispute.created_at >= since)
    )
    if disputes and disputes >= 3:
        result.signals.append(
            Signal("many_disputes", 25, f"{disputes} disputes opened in {WINDOW_DAYS} days.")
        )
    return result


def assess_order(db: Session, order: Order, phones: Counter[str]) -> Assessment:
    result = Assessment("order", order.id, order.brand_id)
    buyer = db.get(User, order.buyer_user_id)
    profile = buyer.reseller_profile if buyer else None
    if order.payment_method == PaymentMethod.COD and order.total_pkr >= BIG_COD_PKR:
        earlier = db.scalar(
            select(func.count())
            .select_from(Order)
            .where(
                Order.buyer_user_id == order.buyer_user_id,
                Order.id != order.id,
                Order.status == OrderStatus.CONFIRMED,
            )
        )
        if not earlier:
            result.signals.append(
                Signal(
                    "big_first_cod",
                    35,
                    f"A first cash on delivery order of Rs {order.total_pkr:,}.",
                )
            )
    if profile and profile.city.strip().lower() != order.delivery_city.strip().lower():
        result.signals.append(
            Signal(
                "city_mismatch",
                15,
                f"Delivery to {order.delivery_city}, but the business is in {profile.city}.",
            )
        )
    if phones[order.delivery_phone] >= SHARED_PHONE_ACCOUNTS:
        result.signals.append(
            Signal("shared_phone", 25, "The delivery number is used by several accounts.")
        )
    return result


def assess_listing(db: Session, lot: Lot, other_brands: list[str]) -> Assessment:
    result = Assessment("listing", lot.id, lot.brand_id)
    if lot.discount_percent >= 90:
        result.signals.append(
            Signal(
                "implausible_discount",
                25,
                f"{lot.discount_percent:.0f}% below the stated retail price.",
            )
        )
    text = f"{lot.title} {lot.description or ''}".lower()
    named = [name for name in other_brands if re.search(rf"\b{re.escape(name.lower())}\b", text)]
    if named:
        result.signals.append(
            Signal(
                "names_another_brand",
                40,
                f"The listing mentions {named[0]}, which is another brand on the platform.",
            )
        )
    latest = db.scalar(
        select(AiOutput.output)
        .join(AiJob, AiJob.id == AiOutput.job_id)
        .where(
            AiJob.feature == AiFeature.RISK_SCORING,
            AiJob.entity_id == lot.id,
        )
        .order_by(AiOutput.created_at.desc())
        .limit(1)
    )
    if isinstance(latest, dict):
        raw_score = latest.get("score")
        score = int(raw_score) if isinstance(raw_score, int | float) else 0
        raw_signals = latest.get("counterfeit_signals")
        counterfeit = list(raw_signals) if isinstance(raw_signals, list) else []
        if counterfeit:
            result.signals.append(
                Signal(
                    "ai_counterfeit_signals",
                    30,
                    "The AI risk check noted: " + "; ".join(str(c) for c in counterfeit)[:200],
                )
            )
        elif score >= 70:
            result.signals.append(
                Signal("ai_risk_score", 20, f"The AI risk check scored this listing {score}.")
            )
    return result


def _upsert(db: Session, assessment: Assessment, now: datetime) -> ReviewCase | None:
    threshold = get_settings().risk_case_threshold
    case = db.scalar(
        select(ReviewCase).where(
            ReviewCase.subject_type == assessment.subject_type,
            ReviewCase.subject_id == assessment.subject_id,
        )
    )
    payload = {"signals": [vars_of(s) for s in assessment.signals]}
    if case is None:
        if assessment.score < threshold:
            return None
        case = ReviewCase(
            subject_type=assessment.subject_type,
            subject_id=assessment.subject_id,
            brand_id=assessment.brand_id,
            score=assessment.score,
            signals=payload,
            status=ReviewStatus.OPEN,
            scored_at=now,
        )
        db.add(case)
        return case
    # A decided case is not reopened by the same evidence; a higher score is new evidence.
    if case.status != ReviewStatus.OPEN and assessment.score <= case.score:
        return case
    if case.status != ReviewStatus.OPEN and assessment.score >= threshold:
        case.status = ReviewStatus.OPEN
    case.score = assessment.score
    case.signals = payload
    case.scored_at = now
    return case


def vars_of(signal: Signal) -> dict[str, object]:
    return {"code": signal.code, "weight": signal.weight, "detail": signal.detail}


def run(db: Session, *, now: datetime | None = None) -> int:
    """Score recent orders, every reseller and every live listing. Returns open cases."""
    moment = now or utcnow()
    phones = _phone_accounts(db)
    since = moment - timedelta(days=WINDOW_DAYS)
    for user in db.scalars(select(User).where(User.role == UserRole.RESELLER)):
        _upsert(db, assess_account(db, user, moment, phones), moment)
    for order in db.scalars(select(Order).where(Order.created_at >= since)):
        _upsert(db, assess_order(db, order, phones), moment)
    brands = {b.id: b.name for b in db.scalars(select(Brand))}
    for lot in db.scalars(select(Lot).where(Lot.status == LotStatus.LIVE)):
        others = [name for brand_id, name in brands.items() if brand_id != lot.brand_id]
        _upsert(db, assess_listing(db, lot, others), moment)
    db.flush()
    return int(
        db.scalar(
            select(func.count())
            .select_from(ReviewCase)
            .where(ReviewCase.status == ReviewStatus.OPEN)
        )
        or 0
    )


def decide(
    db: Session, *, case_id: str, admin: User, outcome: ReviewStatus, action: str, note: str
) -> ReviewCase:
    """A person's decision, with the action they chose. Audited."""
    case = db.get(ReviewCase, case_id)
    if case is None:
        raise NotFound("That case does not exist.")
    if case.status != ReviewStatus.OPEN:
        raise Conflict("This case has already been decided.")
    if outcome == ReviewStatus.OPEN:
        raise ValidationFailed("Clear the case or act on it.")
    if action not in ACTIONS:
        raise ValidationFailed(f"Action must be one of {', '.join(ACTIONS)}.")
    if not note.strip():
        raise ValidationFailed("Write a note saying why.")
    if outcome == ReviewStatus.CLEARED and action != "none":
        raise ValidationFailed("A cleared case takes no action.")

    if action == "suspend_account":
        if case.subject_type != "account":
            raise ValidationFailed("Only an account can be suspended.")
        profile = db.scalar(
            select(ResellerProfile).where(ResellerProfile.user_id == case.subject_id)
        )
        if profile is None:
            raise NotFound("That account has no business profile.")
        profile.status = VerificationStatus.SUSPENDED
    elif action == "pause_listing":
        if case.subject_type != "listing":
            raise ValidationFailed("Only a listing can be paused.")
        lot = db.get(Lot, case.subject_id)
        if lot is None:
            raise NotFound("That listing does not exist.")
        catalog_service.transition(db, lot=lot, to=LotStatus.PAUSED, actor=admin, note=note)

    case.status = outcome
    case.decided_by_user_id = admin.id
    case.decision_note = note.strip()
    case.decided_at = utcnow()
    db.flush()
    audit_service.record(
        db,
        action=f"review_case.{outcome.value}",
        entity_type="review_case",
        entity_id=case.id,
        brand_id=case.brand_id,
        actor_user_id=admin.id,
        actor_role=admin.role,
        after={
            "subject_type": case.subject_type,
            "subject_id": case.subject_id,
            "score": case.score,
            "action": action,
        },
        note=note.strip()[:300],
    )
    return case
