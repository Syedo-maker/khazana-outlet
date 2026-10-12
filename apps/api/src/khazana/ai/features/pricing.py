"""Pricing suggestions.

What this does: suggests a discount band and an expected days to sell range,
with the reasoning shown, and clamps the result to the brand's own policy band.

What it does not do, and will not until Phase 6 produces real sales: predict.
With no sales history a suggestion is informed guesswork dressed in a range,
and this module is built to say so rather than hide it. ``based_on_rules_only``
is carried all the way to the interface for exactly that reason.

Two things are computed here rather than asked of the model:

- The comparable set. A similarity query over past sold lots is a database
  job, and a model asked to recall comparable lots would invent them.
- The clamp. The brand's discount band is a commercial decision that was
  already made, so it is enforced in code and not left to a prompt rule.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from ...core.errors import NotFound, ValidationFailed
from ...models import BrandPolicy, Category, Lot, ManifestLine, Order
from ...models.enums import AiFeature, LotStatus, OrderStatus
from ..gateway import AiResult, run_feature
from ..schemas import PriceSuggestion

logger = logging.getLogger(__name__)

PROMPT = "pricing"

# Below this many comparable sales, a suggestion is rules and judgement rather
# than evidence, and the interface must say so.
EVIDENCE_THRESHOLD = 3
MAX_COMPARABLES = 8


@dataclass(slots=True)
class PricingOutcome:
    suggestion: PriceSuggestion
    result: AiResult
    comparables_used: int
    clamped: bool
    clamp_note: str | None = None

    @property
    def honest_about_evidence(self) -> bool:
        """True when the model admitted it had little to go on.

        Asserted in the eval. A confident price with no comparable sales is
        the failure mode that loses a brand money and then loses the brand.
        """
        return self.comparables_used >= EVIDENCE_THRESHOLD or (self.suggestion.based_on_rules_only)

    def price_range_pkr(self, retail_total: int) -> tuple[int, int]:
        """Convert the discount band into money. The model never sees rupees."""
        high_price = round(
            retail_total * (1 - self.suggestion.suggested_discount_percent_low / 100)
        )
        low_price = round(
            retail_total * (1 - self.suggestion.suggested_discount_percent_high / 100)
        )
        return low_price, high_price


def find_comparables(db: Session, lot: Lot, limit: int = MAX_COMPARABLES) -> list[Lot]:
    """Past lots that actually sold, closest first.

    Same category, then same brand, then anything sold. Only lots with a
    confirmed order count: a lot marked sold with no completed order tells you
    nothing about what a buyer would pay.
    """
    sold_lot_ids = select(Order.lot_id).where(
        Order.status.in_([OrderStatus.CONFIRMED, OrderStatus.DELIVERED])
    )

    same_category = db.scalars(
        select(Lot)
        .where(
            Lot.id != lot.id,
            Lot.category_id == lot.category_id,
            Lot.id.in_(sold_lot_ids),
            Lot.deleted_at.is_(None),
        )
        .order_by(Lot.created_at.desc())
        .limit(limit)
    ).all()

    if len(same_category) >= limit:
        return list(same_category)

    seen = {row.id for row in same_category}
    wider = db.scalars(
        select(Lot)
        .where(
            Lot.id != lot.id,
            Lot.id.in_(sold_lot_ids),
            Lot.deleted_at.is_(None),
        )
        .order_by(Lot.created_at.desc())
        .limit(limit * 2)
    ).all()

    for row in wider:
        if row.id not in seen and len(same_category) < limit:
            same_category = [*same_category, row]
            seen.add(row.id)

    return list(same_category)


def render_comparables(db: Session, lots: list[Lot]) -> str:
    if not lots:
        return (
            "None. No comparable lot has sold on the platform yet, so there is no "
            "evidence to reason from."
        )

    lines = []
    for row in lots:
        retail_total = row.retail_price_per_piece_pkr * row.total_pieces
        discount = round((1 - row.lot_price_pkr / retail_total) * 100) if retail_total else 0
        days = _days_to_sell(db, row)
        lines.append(
            f"- {row.lot_code}: {row.total_pieces} pieces, grade "
            f"{row.condition_grade.value}, sold at {discount} percent off"
            + (f", {days} days to sell" if days is not None else "")
        )
    return "\n".join(lines)


def suggest(
    db: Session,
    lot_id: str,
    *,
    user_id: str | None = None,
    record_fixture: bool = False,
) -> PricingOutcome:
    """Suggest a discount band for one lot."""
    lot = db.get(Lot, lot_id)
    if lot is None or lot.is_deleted:
        raise NotFound("That lot does not exist.")

    policy = db.scalars(select(BrandPolicy).where(BrandPolicy.brand_id == lot.brand_id)).first()
    if policy is None:
        raise ValidationFailed(
            "This brand has no policy row, so there is no allowed discount band to price inside."
        )

    category = db.get(Category, lot.category_id)
    comparables = find_comparables(db, lot)

    result = run_feature(
        db,
        AiFeature.PRICING,
        prompt_name=PROMPT,
        prompt_values={
            "category": category.name if category else "unknown",
            "season": lot.season or "not stated",
            "condition_grade": lot.condition_grade.value,
            "total_pieces": lot.total_pieces,
            "size_spread": _size_spread(db, lot),
            "retail_price": lot.retail_price_per_piece_pkr,
            "lot_price": lot.lot_price_pkr,
            "current_discount": round(lot.discount_percent),
            "age_days": _age_days(lot),
            "title": (lot.title or "")[:200],
            "min_discount": float(policy.min_discount_percent),
            "max_discount": float(policy.max_discount_percent),
            "min_lot_value": policy.min_lot_value_pkr,
            "comparables": render_comparables(db, comparables),
        },
        brand_id=lot.brand_id,
        user_id=user_id,
        entity_type="lot",
        entity_id=lot.id,
        record_fixture=record_fixture,
    )

    suggestion = result.output
    assert isinstance(suggestion, PriceSuggestion)

    suggestion, clamped, note = clamp_to_policy(suggestion, policy)

    # The model is asked to set this honestly. It is also enforced here,
    # because the interface label depends on it and a wrong label is a brand
    # taking a number more seriously than the evidence deserves.
    if len(comparables) < EVIDENCE_THRESHOLD and not suggestion.based_on_rules_only:
        logger.info(
            "pricing for %s had %d comparables, marking as rules based",
            lot.lot_code,
            len(comparables),
        )
        suggestion = suggestion.model_copy(update={"based_on_rules_only": True})

    return PricingOutcome(
        suggestion=suggestion,
        result=result,
        comparables_used=len(comparables),
        clamped=clamped,
        clamp_note=note,
    )


def clamp_to_policy(
    suggestion: PriceSuggestion, policy: BrandPolicy
) -> tuple[PriceSuggestion, bool, str | None]:
    """Hold the suggestion inside the brand's own band.

    The prompt asks the model to stay inside it. This enforces it, because the
    band is a commercial decision the brand already made and a prompt rule is
    not a guarantee. A suggestion outside the band is not a better price, it
    is a broken promise to the brand.
    """
    low_limit = float(policy.min_discount_percent)
    high_limit = float(policy.max_discount_percent)

    low = max(low_limit, min(high_limit, suggestion.suggested_discount_percent_low))
    high = max(low_limit, min(high_limit, suggestion.suggested_discount_percent_high))
    if low > high:
        low, high = high, low

    changed = (
        low != suggestion.suggested_discount_percent_low
        or high != suggestion.suggested_discount_percent_high
    )
    if not changed:
        return suggestion, False, None

    note = (
        f"The suggestion was {suggestion.suggested_discount_percent_low:.0f} to "
        f"{suggestion.suggested_discount_percent_high:.0f} percent, outside this "
        f"brand's band of {low_limit:.0f} to {high_limit:.0f}. It has been held "
        "inside the band."
    )
    logger.warning("pricing suggestion clamped: %s", note)

    return (
        suggestion.model_copy(
            update={
                "suggested_discount_percent_low": low,
                "suggested_discount_percent_high": high,
            }
        ),
        True,
        note,
    )


def _size_spread(db: Session, lot: Lot) -> str:
    """Describe the size curve, which drives clearance more than people expect.

    A lot of 500 pieces that is mostly one size is close to worthless, however
    good the product, so the model is told the shape rather than the total.
    """
    rows = db.scalars(select(ManifestLine).where(ManifestLine.lot_id == lot.id)).all()
    if not rows:
        return "no manifest recorded"

    by_size: dict[str, int] = {}
    for row in rows:
        by_size[row.size] = by_size.get(row.size, 0) + row.pieces

    total = sum(by_size.values()) or 1
    parts = [
        f"{size} {pieces} pieces ({round(pieces / total * 100)} percent)"
        for size, pieces in sorted(by_size.items(), key=lambda item: -item[1])
    ]
    largest = max(by_size.values()) / total
    shape = "concentrated in one size" if largest > 0.5 else "reasonably balanced"
    return f"{', '.join(parts[:8])}. Overall {shape}."


def _age_days(lot: Lot) -> int:
    created = lot.created_at
    if created.tzinfo is None:
        created = created.replace(tzinfo=UTC)
    return max(0, (datetime.now(UTC) - created).days)


def _days_to_sell(db: Session, lot: Lot) -> int | None:
    order = db.scalars(
        select(Order)
        .where(
            Order.lot_id == lot.id,
            Order.status.in_([OrderStatus.CONFIRMED, OrderStatus.DELIVERED]),
        )
        .order_by(Order.created_at)
    ).first()
    if order is None or lot.status not in {LotStatus.SOLD, LotStatus.LIVE}:
        return None

    listed = lot.approved_at or lot.created_at
    placed = order.created_at
    if listed.tzinfo is None:
        listed = listed.replace(tzinfo=UTC)
    if placed.tzinfo is None:
        placed = placed.replace(tzinfo=UTC)
    return max(0, (placed - listed).days)
