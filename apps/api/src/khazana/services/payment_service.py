"""Held funds: money in, held, then released to the brand or returned.

The rules:

- A client redirect never marks anything paid. Only a signed callback, an admin
  confirming a bank transfer, or a recorded cash collection does.
- A repeated callback changes nothing, because each provider event id can be
  stored once.
- An amount that does not match is recorded and does not count as payment.
- Money moves by rule when the buyer confirms, and only people decide refunds.
  No model is involved anywhere in this module.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import timedelta

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..core.errors import Conflict, NotFound, ValidationFailed
from ..models import BrandPolicy, Dispute, Order, Payment, PaymentEvent, Payout, User
from ..models.base import utcnow
from ..models.enums import (
    DisputeStatus,
    OrderStatus,
    PaymentMethod,
    PaymentStatus,
    PayoutStatus,
)
from . import audit_service, order_service
from .payment_providers import Checkout, Outcome, provider_for, wallet_named

logger = logging.getLogger(__name__)

OPEN = (PaymentStatus.PENDING, PaymentStatus.HELD)
REFUNDABLE_ORDERS = frozenset(
    {
        OrderStatus.PAID,
        OrderStatus.PREPARING,
        OrderStatus.SHIPPED,
        OrderStatus.DISPUTED,
    }
)


@dataclass(frozen=True, slots=True)
class ReconciliationItem:
    kind: str
    payment_id: str
    order_code: str
    amount_pkr: int
    detail: str


def current_payment(order: Order) -> Payment | None:
    open_rows = [row for row in order.payments if PaymentStatus(row.status) in OPEN]
    if open_rows:
        return open_rows[0]
    return max(order.payments, key=lambda row: row.created_at, default=None)


def ensure_payment(db: Session, order: Order) -> Payment:
    """The order's open payment, created when there is none.

    A failed attempt leaves the order payable, so a new one can begin.
    """
    existing = current_payment(order)
    if existing is not None and PaymentStatus(existing.status) != PaymentStatus.FAILED:
        return existing
    if OrderStatus(order.status) not in {OrderStatus.AWAITING_PAYMENT, OrderStatus.PREPARING}:
        raise Conflict("This order is not waiting for payment.")

    method = PaymentMethod(order.payment_method)
    provider = provider_for(method)
    payment = Payment(
        method=method,
        status=PaymentStatus.PENDING,
        amount_pkr=order.total_pkr,
        provider=provider.name,
        provider_reference=provider.new_reference(order),
    )
    order.payments.append(payment)
    db.flush()
    return payment


def checkout_for(payment: Payment, order: Order) -> Checkout:
    return provider_for(PaymentMethod(payment.method)).checkout(payment, order)


def ingest_callback(
    db: Session, *, provider_name: str, body: bytes, signature: str | None
) -> Payment | None:
    """Apply one signed provider callback, at most once."""
    provider = wallet_named(provider_name)
    event = provider.parse_callback(body, signature)

    duplicate = db.scalars(
        select(PaymentEvent.id).where(
            PaymentEvent.provider == provider.name,
            PaymentEvent.event_id == event.event_id,
        )
    ).first()
    if duplicate is not None:
        return None

    payment = db.scalars(
        select(Payment)
        .where(Payment.provider == provider.name, Payment.provider_reference == event.reference)
        .with_for_update()
        .execution_options(populate_existing=True)
    ).first()

    try:
        with db.begin_nested():
            db.add(
                PaymentEvent(
                    provider=provider.name,
                    event_id=event.event_id,
                    payment_id=payment.id if payment else None,
                    outcome=event.outcome,
                    payload=event.payload,
                )
            )
    except IntegrityError:
        # A simultaneous delivery of the same event got there first.
        return None

    if payment is None:
        logger.warning("payment callback for unknown reference from %s", provider.name)
        return None

    payment.provider_payload = event.payload
    if PaymentStatus(payment.status) != PaymentStatus.PENDING:
        return payment
    order = order_service.get_order(db, payment.order_id)

    if event.outcome == "failed":
        payment.status = PaymentStatus.FAILED
        payment.failure_reason = "The provider reported that the payment failed."
    elif event.amount_pkr != payment.amount_pkr:
        payment.status = PaymentStatus.FAILED
        payment.failure_reason = (
            f"The provider reported {event.amount_pkr:,} PKR, not {payment.amount_pkr:,} PKR."
        )
    else:
        _hold(db, payment, order, note="Payment received.")
    db.flush()
    return payment


def complete_sandbox_payment(db: Session, *, order: Order, outcome: Outcome) -> Payment:
    """Act as the wallet: send the same signed callback a real one would."""
    payment = ensure_payment(db, order)
    if payment.provider is None or payment.provider_reference is None:
        raise Conflict("This payment is not made through a wallet.")
    if PaymentMethod(payment.method) not in {PaymentMethod.JAZZCASH, PaymentMethod.EASYPAISA}:
        raise Conflict("This payment is not made through a wallet.")
    provider = wallet_named(payment.provider)
    body, signature = provider.build_callback(
        reference=payment.provider_reference,
        outcome=outcome,
        amount_pkr=payment.amount_pkr,
    )
    ingest_callback(db, provider_name=provider.name, body=body, signature=signature)
    return payment


def submit_bank_reference(db: Session, *, order: Order, reference: str) -> Payment:
    payment = ensure_payment(db, order)
    if PaymentMethod(payment.method) != PaymentMethod.BANK_TRANSFER:
        raise Conflict("This order is not being paid by bank transfer.")
    if PaymentStatus(payment.status) != PaymentStatus.PENDING:
        raise Conflict("This payment has already been processed.")
    cleaned = reference.strip()
    if len(cleaned) < 4:
        raise ValidationFailed("Enter the transaction reference from your bank.")
    taken = db.scalars(
        select(Payment.id).where(
            Payment.provider == payment.provider,
            Payment.provider_reference == cleaned,
            Payment.id != payment.id,
        )
    ).first()
    if taken is not None:
        raise Conflict("That bank reference has already been used.")
    payment.provider_reference = cleaned[:120]
    db.flush()
    return payment


def confirm_bank_transfer(
    db: Session, *, payment: Payment, admin: User, ip: str | None = None
) -> Payment:
    """An admin has seen the money arrive in the account."""
    if PaymentMethod(payment.method) != PaymentMethod.BANK_TRANSFER:
        raise Conflict("Only bank transfers are confirmed by hand.")
    if PaymentStatus(payment.status) != PaymentStatus.PENDING:
        raise Conflict("This payment has already been processed.")
    if not payment.provider_reference:
        raise Conflict("The buyer has not entered a bank reference yet.")

    order = order_service.get_order(db, payment.order_id)
    _hold(db, payment, order, note="Bank transfer confirmed.")
    _audit(db, "payment.bank_transfer_confirmed", payment, order, admin, ip=ip)
    return payment


def record_cod_collection(db: Session, order: Order) -> None:
    """The courier delivered and collected the cash."""
    if PaymentMethod(order.payment_method) != PaymentMethod.COD:
        return
    payment = current_payment(order)
    if payment is None or PaymentStatus(payment.status) != PaymentStatus.PENDING:
        return
    payment.status = PaymentStatus.HELD
    payment.held_at = utcnow()
    db.flush()


def on_order_cancelled(db: Session, order: Order) -> None:
    payment = current_payment(order)
    if payment is not None and PaymentStatus(payment.status) == PaymentStatus.PENDING:
        payment.status = PaymentStatus.FAILED
        payment.failure_reason = "The order was cancelled before payment."
        db.flush()


def release_for_order(db: Session, order: Order) -> Payout | None:
    """On confirmation: end the hold and record what the brand is owed.

    Creates the payout record only. Paying it is a separate decision that an
    admin makes in a payout run.
    """
    payment = current_payment(order)
    if payment is None or PaymentStatus(payment.status) != PaymentStatus.HELD:
        return None

    payment.status = PaymentStatus.RELEASED
    payment.released_at = utcnow()

    policy = db.scalars(select(BrandPolicy).where(BrandPolicy.brand_id == order.brand_id)).one()
    payout = Payout(
        order_id=order.id,
        brand_id=order.brand_id,
        amount_pkr=max(0, order.brand_payout_pkr - payment.refunded_pkr),
        status=PayoutStatus.PENDING,
        scheduled_for=utcnow() + timedelta(days=policy.payout_terms_days),
    )
    db.add(payout)
    db.flush()
    return payout


def refund_order(
    db: Session,
    *,
    order: Order,
    admin: User,
    note: str,
    ip: str | None = None,
) -> Order:
    """Return everything the buyer paid and put the stock back."""
    if OrderStatus(order.status) not in REFUNDABLE_ORDERS:
        raise Conflict(f"An order that is {order.status} cannot be refunded.")
    payment = current_payment(order)
    if payment is None or PaymentStatus(payment.status) != PaymentStatus.HELD:
        raise Conflict("There are no held funds on this order to refund.")

    payment.status = PaymentStatus.REFUNDED
    payment.refunded_pkr = payment.amount_pkr
    payment.refunded_at = utcnow()
    order_service.move_to_refunded(db, order, actor=admin, note=note)
    _audit(db, "payment.refunded", payment, order, admin, note=note, ip=ip)
    return order


def resolve_dispute(
    db: Session,
    *,
    dispute: Dispute,
    admin: User,
    resolution: str,
    refund_pkr: int,
    ip: str | None = None,
) -> Order:
    """An admin decides a dispute.

    No refund finds for the seller. A partial refund completes the order with a
    reduced payout, and a full refund reverses the sale.
    """
    if not order_service.is_open_dispute(dispute):
        raise Conflict("This dispute has already been resolved.")
    cleaned = resolution.strip()
    if len(cleaned) < 10:
        raise ValidationFailed("Explain the decision. Both sides will read it.")

    order = order_service.get_order(db, dispute.order_id)
    if OrderStatus(order.status) != OrderStatus.DISPUTED:
        raise Conflict("This order is not in dispute.")
    payment = current_payment(order)
    held = payment is not None and PaymentStatus(payment.status) == PaymentStatus.HELD
    if refund_pkr < 0 or (refund_pkr > 0 and not held):
        raise Conflict("There are no held funds to refund.")
    if payment is not None and refund_pkr > payment.amount_pkr:
        raise ValidationFailed(f"The most that can be refunded is {payment.amount_pkr:,} PKR.")

    dispute.resolution = cleaned
    dispute.refund_pkr = refund_pkr
    dispute.resolved_by_user_id = admin.id
    dispute.resolved_at = utcnow()
    dispute.status = (
        DisputeStatus.RESOLVED_BUYER if refund_pkr > 0 else DisputeStatus.RESOLVED_SELLER
    )

    if payment is not None and refund_pkr == payment.amount_pkr:
        refund_order(db, order=order, admin=admin, note=cleaned, ip=ip)
    else:
        if payment is not None and refund_pkr > 0:
            payment.refunded_pkr = refund_pkr
            payment.refunded_at = utcnow()
        order_service.complete_after_dispute(db, order, actor=admin, note=cleaned)

    audit_service.record(
        db,
        action="dispute.resolved",
        entity_type="dispute",
        entity_id=dispute.id,
        brand_id=order.brand_id,
        actor_user_id=admin.id,
        actor_role=admin.role,
        after={"refund_pkr": refund_pkr, "status": DisputeStatus(dispute.status).value},
        note=cleaned,
        ip=ip,
    )
    return order


def reconciliation(db: Session) -> list[ReconciliationItem]:
    """Payments and orders that disagree, for a person to look at."""
    items: list[ReconciliationItem] = []
    rows = db.execute(select(Payment, Order).join(Order, Order.id == Payment.order_id)).all()
    for payment, order in rows:
        status = PaymentStatus(payment.status)
        order_status = OrderStatus(order.status)
        found: list[tuple[str, str]] = []
        if status == PaymentStatus.HELD and order_status in {
            OrderStatus.CANCELLED,
            OrderStatus.REFUNDED,
            OrderStatus.CONFIRMED,
        }:
            found.append(
                ("held_on_closed_order", f"Funds are held but the order is {order_status.value}.")
            )
        if payment.amount_pkr != order.total_pkr:
            found.append(("amount_mismatch", f"The order total is {order.total_pkr:,} PKR."))
        if status == PaymentStatus.RELEASED and order_status != OrderStatus.CONFIRMED:
            found.append(
                ("released_early", f"Funds were released while the order is {order_status.value}.")
            )
        items.extend(
            ReconciliationItem(kind, payment.id, order.order_code, payment.amount_pkr, detail)
            for kind, detail in found
        )

    missing = db.scalars(
        select(Order)
        .outerjoin(Payout, Payout.order_id == Order.id)
        .join(Payment, Payment.order_id == Order.id)
        .where(
            Order.status == OrderStatus.CONFIRMED,
            Payment.status == PaymentStatus.RELEASED,
            Payout.id.is_(None),
        )
    ).all()
    for order in missing:
        items.append(
            ReconciliationItem(
                "missing_payout", "", order.order_code, order.brand_payout_pkr, "No payout exists."
            )
        )
    return items


def held_total(db: Session) -> int:
    return int(
        db.scalar(
            select(func.coalesce(func.sum(Payment.amount_pkr), 0)).where(
                Payment.status == PaymentStatus.HELD
            )
        )
        or 0
    )


def get_payment(db: Session, payment_id: str) -> Payment:
    payment = db.get(Payment, payment_id)
    if payment is None:
        raise NotFound("That payment does not exist.")
    return payment


def _hold(db: Session, payment: Payment, order: Order, *, note: str) -> None:
    payment.status = PaymentStatus.HELD
    payment.held_at = utcnow()
    if OrderStatus(order.status) == OrderStatus.AWAITING_PAYMENT:
        order_service.mark_paid(db, order, note=note)
    else:
        # Money arrived for an order no longer waiting for it. It stays held,
        # and reconciliation shows it for an admin to return.
        payment.failure_reason = f"Received while the order was {order.status}."
    db.flush()


def _audit(
    db: Session,
    action: str,
    payment: Payment,
    order: Order,
    admin: User,
    *,
    note: str | None = None,
    ip: str | None = None,
) -> None:
    audit_service.record(
        db,
        action=action,
        entity_type="payment",
        entity_id=payment.id,
        brand_id=order.brand_id,
        actor_user_id=admin.id,
        actor_role=admin.role,
        after={"order": order.order_code, "amount_pkr": payment.amount_pkr},
        note=note,
        ip=ip,
    )
