"""The bargaining bot, under docs/decisions/0001-ai-value-bands.md.

The four conditions of that decision, and where each is enforced here:

1. **The floor and step are brand policy rows.** ``bargain_floor_percent``
   and ``bargain_step_percent`` are read from ``brand_policies``; nothing in
   this module holds a price limit of its own.
2. **Every proposal is clamped before it is shown.** ``round_range`` computes
   what this round may offer, the model chooses inside it, and ``clamp``
   forces the answer into it regardless. The model is told only this
   round's range. In the last rounds the lower end of that range can be the
   floor itself, so the eval checks the bot never describes any number as a
   floor, a limit or a minimum.
3. **Every move is audited.** Each counter offer and each agreement is written
   to the append only audit trail with the price before and after.
4. **Off by default, per lot.** ``bargaining_allowed`` needs the brand switch
   on and the lot not refusing, or the lot switched on explicitly. A brand
   that turns it off stops every open negotiation's next round.

An agreement holds the price for the buyer for 48 hours. The buyer orders it
themselves; the bot never places an order.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, timedelta
from math import ceil, floor

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..ai.gateway import run_feature
from ..ai.schemas import BargainReply
from ..config import get_settings
from ..core.errors import Conflict, NotFound, RateLimited, ValidationFailed
from ..models import BrandPolicy, Lot, Negotiation, NegotiationMessage, Order, User, utcnow
from ..models.enums import AiFeature, ChatRole, ConditionGrade, NegotiationStatus, PaymentMethod
from . import audit_service, chat_service, order_service
from .order_service import Delivery, Purchase

MAX_ROUNDS = 5
HOLD_HOURS = 48
HISTORY_MESSAGES = 6


@dataclass(frozen=True, slots=True)
class Band:
    low: int
    high: int


def bargaining_allowed(lot: Lot, policy: BrandPolicy | None) -> bool:
    """Condition 4. Null on the lot inherits the brand; False always refuses."""
    if policy is None or policy.bargain_floor_percent is None:
        return False
    if lot.bargaining_enabled is not None:
        return bool(lot.bargaining_enabled)
    return bool(policy.allow_bargaining)


def floor_price(lot: Lot, policy: BrandPolicy) -> int:
    """The lowest price per piece the brand will accept, rounded up."""
    assert policy.bargain_floor_percent is not None
    return ceil(lot.retail_price_per_piece_pkr * (1 - float(policy.bargain_floor_percent) / 100))


def round_range(negotiation: Negotiation, offer: int | None) -> Band:
    """What this round may offer: at most one step below the current asking
    price, never below the floor, and never below what the buyer offered."""
    low = max(negotiation.floor_price_pkr, negotiation.asking_price_pkr - negotiation.step_pkr)
    if offer is not None:
        low = max(low, min(offer, negotiation.asking_price_pkr))
    return Band(low=min(low, negotiation.asking_price_pkr), high=negotiation.asking_price_pkr)


def clamp(value: int, band: Band) -> int:
    """Condition 2. Whatever the model said, the price is inside the band."""
    return max(band.low, min(band.high, value))


def _policy(db: Session, lot: Lot) -> BrandPolicy | None:
    return db.scalar(select(BrandPolicy).where(BrandPolicy.brand_id == lot.brand_id))


def _audit(
    db: Session, negotiation: Negotiation, action: str, before: int, after: int, kind: str
) -> None:
    audit_service.record(
        db,
        action=action,
        entity_type="negotiation",
        entity_id=negotiation.id,
        brand_id=negotiation.brand_id,
        actor_kind=kind,
        before={"asking_price_pkr": before},
        after={"asking_price_pkr": after, "round": negotiation.rounds},
    )


def _say(
    db: Session,
    negotiation: Negotiation,
    role: ChatRole,
    body: str,
    *,
    offer: int | None = None,
    proposed: int | None = None,
    clamped: bool = False,
) -> NegotiationMessage:
    message = NegotiationMessage(
        negotiation_id=negotiation.id,
        brand_id=negotiation.brand_id,
        role=role,
        body=body,
        offer_pkr=offer,
        proposed_pkr=proposed,
        clamped=clamped,
        created_at=utcnow(),
    )
    # Appended through the relationship, so a negotiation already loaded in
    # this session shows its new messages without a reload.
    negotiation.messages.append(message)
    db.flush()
    return message


def rounds_today(db: Session, buyer_user_id: str) -> int:
    """How many bargaining messages this buyer has sent since midnight in Pakistan."""
    from .chat_service import start_of_pakistan_day

    since = start_of_pakistan_day(utcnow())
    count = db.scalar(
        select(func.count())
        .select_from(NegotiationMessage)
        .join(Negotiation, Negotiation.id == NegotiationMessage.negotiation_id)
        .where(
            Negotiation.buyer_user_id == buyer_user_id,
            NegotiationMessage.role == ChatRole.BUYER,
            NegotiationMessage.created_at >= since,
        )
    )
    return int(count or 0)


def get_for_buyer(db: Session, *, buyer: User, negotiation_id: str) -> Negotiation:
    negotiation = db.get(Negotiation, negotiation_id)
    if negotiation is None or negotiation.buyer_user_id != buyer.id:
        raise NotFound("That negotiation does not exist.")
    _expire_if_due(negotiation)
    return negotiation


def _expire_if_due(negotiation: Negotiation) -> None:
    if negotiation.status != NegotiationStatus.AGREED or negotiation.agreed_until is None:
        return
    until = negotiation.agreed_until
    if until.tzinfo is None:
        until = until.replace(tzinfo=UTC)
    if until <= utcnow():
        negotiation.status = NegotiationStatus.EXPIRED


def start(db: Session, *, buyer: User, lot_id: str, message: str, offer: int | None) -> Negotiation:
    """Open a negotiation on a whole lot and answer the first message."""
    order_service.require_buyer(db, buyer)
    profile = buyer.reseller_profile
    city = profile.city if profile else ""
    lot = order_service.buyable_lot(db, lot_id=lot_id, city=city)
    policy = _policy(db, lot)
    if not bargaining_allowed(lot, policy):
        raise Conflict("The price of this lot is fixed. It is not open to bargaining.")
    assert policy is not None
    list_price = ceil(lot.lot_price_pkr / lot.total_pieces)
    bottom = floor_price(lot, policy)
    if bottom >= list_price:
        raise Conflict("The price of this lot is fixed. It is not open to bargaining.")

    existing = db.scalar(
        select(Negotiation).where(
            Negotiation.lot_id == lot.id,
            Negotiation.buyer_user_id == buyer.id,
            Negotiation.status.in_([NegotiationStatus.OPEN, NegotiationStatus.AGREED]),
        )
    )
    if existing is not None:
        # A lapsed hold is only marked expired when it is read, so read it now.
        _expire_if_due(existing)
        db.flush()
    if existing is not None and existing.status != NegotiationStatus.EXPIRED:
        raise Conflict("You already have a negotiation open on this lot.")

    negotiation = Negotiation(
        lot_id=lot.id,
        brand_id=lot.brand_id,
        buyer_user_id=buyer.id,
        status=NegotiationStatus.OPEN,
        pieces=lot.available_pieces,
        list_price_pkr=list_price,
        floor_price_pkr=bottom,
        step_pkr=max(
            1, floor(lot.retail_price_per_piece_pkr * float(policy.bargain_step_percent) / 100)
        ),
        asking_price_pkr=list_price,
        rounds=0,
    )
    db.add(negotiation)
    db.flush()
    return respond(db, buyer=buyer, negotiation=negotiation, message=message, offer=offer)


def respond(
    db: Session, *, buyer: User, negotiation: Negotiation, message: str, offer: int | None
) -> Negotiation:
    """One round: the buyer speaks, the bot answers inside the band."""
    if negotiation.status != NegotiationStatus.OPEN:
        raise Conflict("This negotiation is closed.")
    text = " ".join(message.split())[:1_000]
    if not text and offer is None:
        raise ValidationFailed("Say something or make an offer.")
    if offer is not None and offer < 1:
        raise ValidationFailed("An offer must be at least 1 rupee.")

    # Each round is a model call paid from the brand's AI budget, so a buyer's
    # rounds count against the same daily limit as their assistant messages.
    limit = get_settings().assistant_daily_message_limit
    used = rounds_today(db, buyer.id) + chat_service.messages_sent_today(db, buyer.id)
    if used >= limit:
        raise RateLimited(
            f"You have made {limit} offers and messages today. "
            "The limit resets at midnight Pakistan time."
        )

    lot = db.get(Lot, negotiation.lot_id)
    policy = _policy(db, lot) if lot else None
    if lot is None or not bargaining_allowed(lot, policy):
        # Returned rather than raised: an error would roll the status back with
        # the request, leaving the negotiation open in the database.
        negotiation.status = NegotiationStatus.WITHDRAWN
        _say(
            db,
            negotiation,
            ChatRole.ASSISTANT,
            "The brand has closed this lot to bargaining. You can still buy it at "
            "the listed price.\nBrand ne is lot par bhao taao band kar diya hai. "
            "Aap ise likhi qeemat par khareed saktay hain.",
        )
        db.flush()
        return negotiation

    history = [
        f"{'Buyer' if m.role == ChatRole.BUYER else 'You'}: {m.body}"
        for m in negotiation.messages[-HISTORY_MESSAGES:]
    ]
    _say(db, negotiation, ChatRole.BUYER, text or f"Offer: Rs {offer}", offer=offer)
    negotiation.rounds += 1
    before = negotiation.asking_price_pkr

    # An offer at or above what this round could reach is simply accepted.
    band = round_range(negotiation, offer)
    if offer is not None and offer >= band.low:
        return _agree(db, negotiation, min(offer, negotiation.asking_price_pkr), kind="ai")

    if negotiation.rounds > MAX_ROUNDS:
        body = (
            f"Rs {negotiation.asking_price_pkr} per piece is my best price for this lot.\n"
            f"Is lot ke liye Rs {negotiation.asking_price_pkr} fi piece aakhri qeemat hai."
        )
        _say(db, negotiation, ChatRole.ASSISTANT, body)
        return negotiation

    grade = ConditionGrade(lot.condition_grade)
    result = run_feature(
        db,
        AiFeature.BARGAINING,
        prompt_name="bargaining",
        prompt_values={
            "lot_title": lot.title,
            "condition": f"{grade.value}",
            "pieces": negotiation.pieces,
            "list_price_pkr": negotiation.list_price_pkr,
            "current_asking_pkr": negotiation.asking_price_pkr,
            "buyer_offer_pkr": "none given" if offer is None else offer,
            "allowed_low_pkr": band.low,
            "allowed_high_pkr": band.high,
            "round_number": negotiation.rounds,
            "max_rounds": MAX_ROUNDS,
            "message": text or f"I offer Rs {offer} per piece.",
            "history": "\n".join(history) or "No earlier messages.",
        },
        output_schema=BargainReply,
        brand_id=negotiation.brand_id,
        user_id=buyer.id,
        entity_type="negotiation",
        entity_id=negotiation.id,
    )
    reply = result.output
    assert isinstance(reply, BargainReply)

    counter = clamp(reply.counter_price_per_piece_pkr, band)
    was_clamped = counter != reply.counter_price_per_piece_pkr
    body = reply.message
    if was_clamped:
        # The model's words named a price the clamp did not allow, so the
        # buyer is told the real one rather than a sentence that is now wrong.
        body = f"Rs {counter} per piece.\nRs {counter} fi piece."
    negotiation.asking_price_pkr = counter
    _say(
        db,
        negotiation,
        ChatRole.ASSISTANT,
        body,
        proposed=reply.counter_price_per_piece_pkr,
        clamped=was_clamped,
    )
    _audit(db, negotiation, "negotiation.counter", before, counter, audit_service.ACTOR_AI)
    db.flush()
    return negotiation


def _agree(db: Session, negotiation: Negotiation, price: int, *, kind: str) -> Negotiation:
    # Condition 2 holds for agreements too: never below the floor.
    price = max(price, negotiation.floor_price_pkr)
    before = negotiation.asking_price_pkr
    negotiation.status = NegotiationStatus.AGREED
    negotiation.agreed_price_pkr = price
    negotiation.asking_price_pkr = price
    negotiation.agreed_until = utcnow() + timedelta(hours=HOLD_HOURS)
    _say(
        db,
        negotiation,
        ChatRole.ASSISTANT,
        f"Agreed: Rs {price} per piece for {negotiation.pieces} pieces, held for you for "
        f"{HOLD_HOURS} hours. Place the order when you are ready.\n"
        f"Theek hai: {negotiation.pieces} pieces Rs {price} fi piece, {HOLD_HOURS} ghante "
        "ke liye aap ke liye rakh diya. Jab chahein order karein.",
    )
    _audit(db, negotiation, "negotiation.agreed", before, price, kind)
    db.flush()
    return negotiation


def accept(db: Session, *, buyer: User, negotiation_id: str) -> Negotiation:
    """The buyer takes the current asking price."""
    negotiation = get_for_buyer(db, buyer=buyer, negotiation_id=negotiation_id)
    if negotiation.status != NegotiationStatus.OPEN:
        raise Conflict("This negotiation is closed.")
    return _agree(db, negotiation, negotiation.asking_price_pkr, kind=audit_service.ACTOR_USER)


def order(
    db: Session,
    *,
    buyer: User,
    negotiation_id: str,
    delivery: Delivery,
    method: PaymentMethod,
    ip: str | None = None,
) -> Order:
    """Order the whole lot at the agreed price, while the hold lasts."""
    negotiation = get_for_buyer(db, buyer=buyer, negotiation_id=negotiation_id)
    if negotiation.status != NegotiationStatus.AGREED or negotiation.agreed_price_pkr is None:
        raise Conflict("There is no agreed price to order at, or the 48 hour hold has passed.")
    if negotiation.agreed_price_pkr < negotiation.floor_price_pkr:
        raise Conflict("The agreed price is below the brand's floor.")
    [placed] = order_service.place_orders(
        db,
        buyer=buyer,
        purchases=[Purchase(lot_id=negotiation.lot_id)],
        delivery=delivery,
        method=method,
        ip=ip,
        agreed_prices={negotiation.lot_id: negotiation.agreed_price_pkr},
    )
    if placed.pieces != negotiation.pieces:
        raise Conflict("The lot has changed since you agreed a price. Start a new negotiation.")
    negotiation.status = NegotiationStatus.ORDERED
    negotiation.order_id = placed.id
    db.flush()
    return placed
