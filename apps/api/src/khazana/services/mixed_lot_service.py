"""The mixed lot builder.

A single shop rarely wants three hundred pieces of one design. This builds a
mixed lot instead: slow stock from several brands, sized to the buyer's budget,
categories and piece count.

What a mixed lot is, precisely: a set of ordinary part lot purchases, one per
brand, proposed together. It is not a new listing. That is deliberate, because
it means nothing about brand control changes:

- Each part is priced by ``order_service.price_purchase``, the same function
  checkout uses, so each brand's minimum order, minimum value, part lot
  policy, region lock and commission apply unchanged.
- Each part becomes its own order with its own brand at checkout, so payouts,
  disputes and the dispute window work as they already do.
- Each part is presented through the catalogue's own rules, so an unbranded
  lot stays unbranded inside a mixed lot.

Only lots whose brand allows part lot orders are used, unless the whole lot
fits. The builder proposes; the buyer adds the proposal to the cart and checks
out as normal.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from datetime import UTC

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from ..core.errors import AppError, ValidationFailed
from ..models import BrandPolicy, CartItem, Lot, Order, User, utcnow
from ..models.enums import OrderStatus, UserRole, VerificationStatus
from . import approval_service, order_service
from .order_service import LineChoice, Purchase

CANDIDATES = 150
MAX_BRANDS = 6
SOLD = (
    OrderStatus.PAID,
    OrderStatus.PREPARING,
    OrderStatus.SHIPPED,
    OrderStatus.DELIVERED,
    OrderStatus.CONFIRMED,
    OrderStatus.DISPUTED,
)


@dataclass(slots=True)
class Component:
    lot: Lot
    pieces: int
    lines: list[LineChoice]
    subtotal_pkr: int
    shipping_pkr: int
    reason: str

    @property
    def total_pkr(self) -> int:
        return self.subtotal_pkr + self.shipping_pkr


@dataclass(slots=True)
class MixedLotProposal:
    components: list[Component]
    budget_pkr: int
    target_pieces: int
    notes: list[str] = field(default_factory=list)

    @property
    def pieces(self) -> int:
        return sum(c.pieces for c in self.components)

    @property
    def total_pkr(self) -> int:
        return sum(c.total_pkr for c in self.components)

    @property
    def brand_count(self) -> int:
        return len({c.lot.brand_id for c in self.components})


def spread_lines(available: list[LineChoice], pieces: int) -> list[LineChoice]:
    """Take ``pieces`` across sizes and colours as evenly as stock allows.

    A shop wants a size run, not 60 pieces of one size, so pieces are taken
    one at a time around the available lines.
    """
    stock = {(line.size, line.color): line.pieces for line in available}
    taken: Counter[tuple[str, str]] = Counter()
    order = sorted(stock)
    remaining = min(pieces, sum(stock.values()))
    while remaining > 0:
        progressed = False
        for key in order:
            if remaining == 0:
                break
            if taken[key] < stock[key]:
                taken[key] += 1
                remaining -= 1
                progressed = True
        if not progressed:
            break
    return [LineChoice(size=s, color=c, pieces=n) for (s, c), n in sorted(taken.items()) if n]


def _sold_share(db: Session, lots: list[Lot]) -> dict[str, float]:
    if not lots:
        return {}
    rows = db.execute(
        select(Order.lot_id, func.coalesce(func.sum(Order.pieces), 0))
        .where(Order.lot_id.in_([lot.id for lot in lots]), Order.status.in_(SOLD))
        .group_by(Order.lot_id)
    ).all()
    sold = {lot_id: int(pieces) for lot_id, pieces in rows}
    return {lot.id: sold.get(lot.id, 0) / lot.total_pieces for lot in lots if lot.total_pieces}


def _days_live(lot: Lot) -> int:
    if lot.approved_at is None:
        return 0
    approved = lot.approved_at
    if approved.tzinfo is None:
        approved = approved.replace(tzinfo=UTC)
    return (utcnow() - approved).days


def build(
    db: Session,
    *,
    user: User,
    budget_pkr: int,
    target_pieces: int,
    city: str,
    category_ids: tuple[str, ...] = (),
    max_brands: int = 4,
) -> MixedLotProposal:
    if budget_pkr < 1 or target_pieces < 1:
        raise ValidationFailed("Give a budget and a number of pieces.")
    max_brands = max(2, min(max_brands, MAX_BRANDS))
    profile = user.reseller_profile
    verified = (
        profile is not None and VerificationStatus(profile.status) == VerificationStatus.VERIFIED
    )

    statement = (
        select(Lot)
        .where(
            approval_service.visibility_filter(
                role=UserRole.RESELLER, reseller_is_verified=verified, city=city
            ),
            Lot.total_pieces > Lot.reserved_pieces,
        )
        .options(selectinload(Lot.manifest_lines))
        .limit(CANDIDATES)
    )
    if category_ids:
        statement = statement.where(Lot.category_id.in_(category_ids))
    candidates = list(db.scalars(statement))
    policies = {
        p.brand_id: p
        for p in db.scalars(
            select(BrandPolicy).where(BrandPolicy.brand_id.in_({c.brand_id for c in candidates}))
        )
    }
    sold = _sold_share(db, candidates)

    # Slowest stock first, the reason this feature exists, then the deeper
    # discount, then stock already in the buyer's city.
    wanted_city = city.strip().lower()
    candidates.sort(
        key=lambda lot: (
            sold.get(lot.id, 0.0),
            -_days_live(lot),
            -lot.discount_percent,
            lot.stock_city.strip().lower() != wanted_city,
        )
    )

    def eligible(lot: Lot) -> bool:
        policy = policies.get(lot.brand_id)
        return bool(policy and policy.allow_part_lot_orders) or (
            lot.available_pieces <= target_pieces
        )

    # Shares are split across the brands that can actually contribute, so two
    # brands with stock each get half the target rather than a quarter.
    brand_slots = min(max_brands, len({lot.brand_id for lot in candidates if eligible(lot)}))

    proposal = MixedLotProposal(components=[], budget_pkr=budget_pkr, target_pieces=target_pieces)
    used_brands: set[str] = set()
    for lot in candidates:
        if len(used_brands) >= max_brands or proposal.pieces >= target_pieces:
            break
        if lot.brand_id in used_brands:
            continue
        policy = policies.get(lot.brand_id)
        available = lot.available_pieces
        whole_fits = available <= target_pieces - proposal.pieces
        if not (policy and policy.allow_part_lot_orders) and not whole_fits:
            continue

        slots_left = max(1, brand_slots - len(used_brands))
        share = max(1, (target_pieces - proposal.pieces) // slots_left)
        unit = -(-lot.lot_price_pkr // lot.total_pieces)
        floor_pieces = lot.min_order_pieces
        if policy and policy.min_lot_value_pkr:
            floor_pieces = max(floor_pieces, -(-policy.min_lot_value_pkr // unit))
        pieces = min(available, max(share, floor_pieces))
        component = _priced(db, lot, pieces, city, budget_pkr - proposal.total_pkr)
        if component is None:
            continue
        proposal.components.append(component)
        used_brands.add(lot.brand_id)

    if proposal.brand_count < 2:
        proposal.notes.append(
            "Not enough brands have matching stock that can be bought in part, so "
            "this is not a mixed lot yet. Widen the categories or raise the budget."
        )
    if proposal.pieces < target_pieces:
        proposal.notes.append(
            f"Found {proposal.pieces} of the {target_pieces} pieces asked for within the budget."
        )
    return proposal


def _priced(db: Session, lot: Lot, pieces: int, city: str, budget_left: int) -> Component | None:
    """Price one part, shrinking it to the budget, or None if it cannot fit."""
    available = order_service.available_lines(db, lot)
    while pieces >= 1:
        lines = spread_lines(available, pieces)
        whole = sum(line.pieces for line in lines) == lot.available_pieces
        purchase = Purchase(lot_id=lot.id, whole_lot=whole, lines=() if whole else tuple(lines))
        try:
            pricing = order_service.price_purchase(
                db, lot=lot, purchase=purchase, destination_city=city
            )
        except AppError:
            return None
        if pricing.total_pkr <= budget_left:
            return Component(
                lot=lot,
                pieces=pricing.pieces,
                lines=pricing.lines,
                subtotal_pkr=pricing.subtotal_pkr,
                shipping_pkr=pricing.shipping_pkr,
                reason=_reason(lot),
            )
        smaller = int(pieces * budget_left / pricing.total_pkr)
        if smaller >= pieces:
            smaller = pieces - 1
        if smaller < lot.min_order_pieces:
            return None
        pieces = smaller
    return None


def _reason(lot: Lot) -> str:
    days = _days_live(lot)
    return f"{round(lot.discount_percent)}% below retail, on sale for {days} days"


def add_to_cart(db: Session, *, user: User, proposal: MixedLotProposal) -> list[CartItem]:
    """Put every part of a proposal in the cart, as ordinary cart items."""
    items = []
    for component in proposal.components:
        whole = component.pieces == component.lot.available_pieces
        items.append(
            order_service.set_cart_item(
                db,
                user=user,
                purchase=Purchase(
                    lot_id=component.lot.id,
                    whole_lot=whole,
                    lines=() if whole else tuple(component.lines),
                ),
            )
        )
    return items
