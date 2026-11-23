"""Matching unsellable stock with tailors, artisans, NGOs and recyclers.

The brand asks for matches for one of its lots and offers the lot to a
partner, as a donation or a token price sale. An administrator, who holds the
partner's contact details, arranges the handover and records it as accepted
and then collected. When a partner accepts, the lot is withdrawn from sale,
because the same pieces cannot be sold and given away.

Ranking is plain and explained: partners in the lot's own city first, then
those who take this category, then those whose piece range fits.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..core.errors import Conflict, NotFound, ValidationFailed
from ..models import Category, Lot, Partner, Redirection, User, utcnow
from ..models.enums import ConditionGrade, LotStatus, RedirectStatus
from . import audit_service, catalog_service

ROUTES = ("donation", "upcycle_sale")
KINDS = ("tailor", "artisan", "ngo", "recycler")
NOT_REDIRECTABLE = (LotStatus.SOLD, LotStatus.WITHDRAWN)


@dataclass(slots=True)
class Match:
    partner: Partner
    score: int
    reasons: list[str] = field(default_factory=list)


def _words(partner: Partner) -> list[str]:
    return [str(w).lower() for w in (partner.categories or {}).get("words", [])]


def matches(db: Session, lot: Lot) -> list[Match]:
    category = db.get(Category, lot.category_id)
    name = (category.name if category else "").lower()
    grade = ConditionGrade(lot.condition_grade).value
    pieces = lot.available_pieces
    out = []
    for partner in db.scalars(select(Partner).where(Partner.is_active.is_(True))):
        grades = [str(g) for g in (partner.grades or {}).get("grades", [])]
        if grades and grade not in grades:
            continue
        words = _words(partner)
        if words and not any(word in name for word in words):
            continue
        if partner.max_pieces is not None and pieces > partner.max_pieces:
            continue
        score, reasons = 0, []
        if partner.city.strip().lower() == lot.stock_city.strip().lower():
            score += 2
            reasons.append(f"In {lot.stock_city}, where the stock is")
        if words:
            score += 1
            reasons.append(f"Takes {category.name if category else 'this category'}")
        if pieces >= partner.min_pieces:
            score += 1
        else:
            reasons.append(f"Prefers at least {partner.min_pieces} pieces")
        out.append(Match(partner=partner, score=score, reasons=reasons))
    out.sort(key=lambda m: (-m.score, m.partner.name))
    return out


def propose(
    db: Session,
    *,
    lot: Lot,
    partner_id: str,
    route: str,
    price_pkr: int,
    actor: User,
    note: str = "",
) -> Redirection:
    if route not in ROUTES:
        raise ValidationFailed("Choose donation or upcycle sale.")
    if route == "donation" and price_pkr != 0:
        raise ValidationFailed("A donation has no price.")
    if price_pkr < 0:
        raise ValidationFailed("A price cannot be negative.")
    if LotStatus(lot.status) in NOT_REDIRECTABLE:
        raise Conflict("This lot is sold or withdrawn.")
    if lot.reserved_pieces:
        raise Conflict("This lot has orders in progress. Finish or cancel them first.")
    partner = db.get(Partner, partner_id)
    if partner is None or not partner.is_active:
        raise NotFound("That partner is not available.")
    open_one = db.scalar(
        select(Redirection).where(
            Redirection.lot_id == lot.id,
            Redirection.status.in_([RedirectStatus.PROPOSED, RedirectStatus.ACCEPTED]),
        )
    )
    if open_one is not None:
        raise Conflict("This lot has already been offered to a partner.")
    redirection = Redirection(
        lot_id=lot.id,
        brand_id=lot.brand_id,
        partner_id=partner.id,
        route=route,
        pieces=lot.available_pieces,
        price_pkr=price_pkr,
        status=RedirectStatus.PROPOSED,
        note=note,
    )
    db.add(redirection)
    db.flush()
    _audit(db, redirection, "redirection.proposed", actor)
    return redirection


def move(db: Session, *, redirection_id: str, to: RedirectStatus, actor: User) -> Redirection:
    """Record what happened. Administrators only; the caller checks."""
    redirection = db.get(Redirection, redirection_id)
    if redirection is None:
        raise NotFound("That redirection does not exist.")
    current = RedirectStatus(redirection.status)
    allowed = {
        RedirectStatus.PROPOSED: {RedirectStatus.ACCEPTED, RedirectStatus.CANCELLED},
        RedirectStatus.ACCEPTED: {RedirectStatus.COLLECTED, RedirectStatus.CANCELLED},
    }
    if to not in allowed.get(current, set()):
        raise Conflict(f"A redirection that is {current.value} cannot become {to.value}.")
    if to == RedirectStatus.ACCEPTED:
        lot = db.get(Lot, redirection.lot_id)
        # The lot stayed on sale while the offer was open, so check it again.
        if lot is None or LotStatus(lot.status) in NOT_REDIRECTABLE:
            raise Conflict("The lot was sold or withdrawn since it was offered.")
        if lot.reserved_pieces:
            raise Conflict("The lot has orders in progress since it was offered.")
        redirection.pieces = lot.available_pieces
    redirection.status = to
    if to == RedirectStatus.ACCEPTED:
        lot = db.get(Lot, redirection.lot_id)
        withdrawable = (
            catalog_service.TRANSITIONS.get(LotStatus(lot.status), frozenset())
            if lot is not None
            else frozenset()
        )
        if lot is not None and LotStatus.WITHDRAWN in withdrawable:
            catalog_service.transition(
                db, lot=lot, to=LotStatus.WITHDRAWN, actor=actor, note="Given to a partner"
            )
    if to == RedirectStatus.COLLECTED:
        redirection.collected_at = utcnow()
    db.flush()
    _audit(db, redirection, f"redirection.{to.value}", actor)
    return redirection


def _audit(db: Session, redirection: Redirection, action: str, actor: User) -> None:
    audit_service.record(
        db,
        action=action,
        entity_type="redirection",
        entity_id=redirection.id,
        brand_id=redirection.brand_id,
        actor_user_id=actor.id,
        actor_role=actor.role,
        after={
            "lot_id": redirection.lot_id,
            "partner_id": redirection.partner_id,
            "route": redirection.route,
            "pieces": redirection.pieces,
            "price_pkr": redirection.price_pkr,
            "status": RedirectStatus(redirection.status).value,
        },
    )
