"""The smart markdown agent, under docs/decisions/0001-ai-value-bands.md.

On a schedule, it looks at each live lot whose brand switched it on and
decides whether to lower the price, and by how much. The four conditions:

1. **Step, interval and floor are brand policy rows.** ``markdown_step_percent``,
   ``markdown_interval_days`` and ``markdown_floor_percent``. A lot reaches its
   floor only through a number of steps, never in one jump.
2. **Every decision is clamped.** The model chooses a reduction between zero
   and the step; ``clamp_reduction`` forces it there, and the new discount is
   then held at the floor and inside the brand's advertised band.
3. **Every change is audited** with the price before and after and the
   model's reason.
4. **Off by default, per lot.** The brand switch and the lot switch work as
   they do for bargaining.

Lots with pieces reserved by an order in progress are skipped, so an order is
never priced against a lot total that moved underneath it.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from math import floor

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..ai.gateway import run_feature
from ..ai.schemas import MarkdownDecision
from ..models import BrandPolicy, Category, Lot, Order, utcnow
from ..models.enums import AiFeature, LotStatus, OrderStatus
from . import audit_service

SOLD = (
    OrderStatus.PAID,
    OrderStatus.PREPARING,
    OrderStatus.SHIPPED,
    OrderStatus.DELIVERED,
    OrderStatus.CONFIRMED,
    OrderStatus.DISPUTED,
)


@dataclass(slots=True)
class MarkdownResult:
    lot_id: str
    lot_code: str
    before_percent: float
    after_percent: float
    proposed_percent: float
    reason: str

    @property
    def changed(self) -> bool:
        return self.after_percent != self.before_percent


def markdown_allowed(lot: Lot, policy: BrandPolicy | None) -> bool:
    if policy is None or policy.markdown_floor_percent is None:
        return False
    if lot.auto_markdown_enabled is not None:
        return bool(lot.auto_markdown_enabled)
    return bool(policy.allow_auto_markdown)


def clamp_reduction(value: float, step: float) -> float:
    return max(0.0, min(step, float(value)))


def _aware(value: datetime | None) -> datetime | None:
    if value is not None and value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value


def _due(lot: Lot, policy: BrandPolicy, now: datetime) -> bool:
    last = _aware(lot.last_markdown_at) or _aware(lot.approved_at)
    if last is None:
        return False
    return (now - last).days >= policy.markdown_interval_days


def new_lot_price(lot: Lot, discount_percent: float) -> int:
    """The lot price for a discount, rounded down to a whole rupee per piece."""
    per_piece = floor(lot.retail_price_per_piece_pkr * (1 - discount_percent / 100))
    return per_piece * lot.total_pieces


def run(db: Session, *, now: datetime | None = None) -> list[MarkdownResult]:
    """One scheduled pass over every lot the agent may touch."""
    moment = now or utcnow()
    lots = db.scalars(
        select(Lot).where(
            Lot.status == LotStatus.LIVE,
            Lot.deleted_at.is_(None),
            Lot.reserved_pieces == 0,
        )
    ).all()
    policies = {
        p.brand_id: p
        for p in db.scalars(
            select(BrandPolicy).where(BrandPolicy.brand_id.in_({lot.brand_id for lot in lots}))
        )
    }
    results = []
    for lot in lots:
        policy = policies.get(lot.brand_id)
        if not markdown_allowed(lot, policy):
            continue
        assert policy is not None
        if not _due(lot, policy, moment):
            continue
        result = mark_down(db, lot=lot, policy=policy, now=moment)
        if result is not None:
            results.append(result)
    return results


def mark_down(
    db: Session, *, lot: Lot, policy: BrandPolicy, now: datetime
) -> MarkdownResult | None:
    assert policy.markdown_floor_percent is not None
    # The agent may not go deeper than its own floor or the advertised band.
    ceiling = min(float(policy.markdown_floor_percent), float(policy.max_discount_percent))
    current = lot.discount_percent
    if current >= ceiling:
        return None
    step = float(policy.markdown_step_percent)

    sold = int(
        db.scalar(
            select(func.coalesce(func.sum(Order.pieces), 0)).where(
                Order.lot_id == lot.id, Order.status.in_(SOLD)
            )
        )
        or 0
    )
    approved = _aware(lot.approved_at) or now
    last = _aware(lot.last_markdown_at) or approved
    category = db.get(Category, lot.category_id)

    result = run_feature(
        db,
        AiFeature.MARKDOWN,
        prompt_name="markdown",
        prompt_values={
            "lot_title": lot.title,
            "category": category.name if category else "Clothing",
            "season": lot.season or "not given",
            "days_live": (now - approved).days,
            "days_since_last_change": (now - last).days,
            "pieces": lot.total_pieces,
            "pieces_sold": sold,
            "sell_through_percent": round(100 * sold / lot.total_pieces) if lot.total_pieces else 0,
            "current_discount_percent": round(current),
            "step_percent": round(step, 2),
            "today": now.date().isoformat(),
        },
        output_schema=MarkdownDecision,
        brand_id=lot.brand_id,
        entity_type="lot",
        entity_id=lot.id,
    )
    decision = result.output
    assert isinstance(decision, MarkdownDecision)

    reduction = clamp_reduction(decision.reduce_by_percent, step)
    target = min(ceiling, current + reduction)
    before_price = lot.lot_price_pkr
    after_price = new_lot_price(lot, target)
    # Rounding a piece price down can never take the lot past the ceiling.
    while after_price < before_price and _discount(lot, after_price) > ceiling:
        after_price += lot.total_pieces

    lot.last_markdown_at = now
    outcome = MarkdownResult(
        lot_id=lot.id,
        lot_code=lot.lot_code,
        before_percent=round(current, 2),
        after_percent=round(current, 2),
        proposed_percent=float(decision.reduce_by_percent),
        reason=decision.reason,
    )
    if after_price < before_price:
        lot.lot_price_pkr = after_price
        outcome.after_percent = round(lot.discount_percent, 2)
        audit_service.record(
            db,
            action="lot.marked_down",
            entity_type="lot",
            entity_id=lot.id,
            brand_id=lot.brand_id,
            actor_kind=audit_service.ACTOR_AI,
            before={"lot_price_pkr": before_price, "discount_percent": round(current, 2)},
            after={"lot_price_pkr": after_price, "discount_percent": outcome.after_percent},
            note=decision.reason[:300],
        )
    db.flush()
    return outcome


def _discount(lot: Lot, lot_price: int) -> float:
    retail_total = lot.retail_price_per_piece_pkr * lot.total_pieces
    return (1 - lot_price / retail_total) * 100 if retail_total else 0.0
