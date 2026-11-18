"""Paying for an order, and the provider callback.

The callback has no bearer token. Its signature is the authentication, and it
is checked against the raw request body before anything is parsed.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Header, Request
from pydantic import BaseModel, ConfigDict, Field

from ...core.errors import NotFound
from ...models import Order, Payment
from ...models.enums import PaymentMethod, PaymentStatus
from ...services import order_service, payment_service
from ..deps import CurrentPrincipal, Db, Principal

router = APIRouter(tags=["payments"])


class PaymentOut(BaseModel):
    id: str
    method: PaymentMethod
    status: PaymentStatus
    amount_pkr: int
    refunded_pkr: int
    reference: str | None
    failure_reason: str | None
    held_at: datetime | None
    released_at: datetime | None
    action: str | None = None
    instructions: str | None = None


class SandboxOutcomeIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    outcome: Literal["succeeded", "failed"] = "succeeded"


class BankReferenceIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reference: str = Field(min_length=4, max_length=120)


def payment_out(payment: Payment, order: Order) -> PaymentOut:
    checkout = (
        payment_service.checkout_for(payment, order)
        if PaymentStatus(payment.status) == PaymentStatus.PENDING
        else None
    )
    return PaymentOut(
        id=payment.id,
        method=payment.method,
        status=payment.status,
        amount_pkr=payment.amount_pkr,
        refunded_pkr=payment.refunded_pkr,
        reference=payment.provider_reference,
        failure_reason=payment.failure_reason,
        held_at=payment.held_at,
        released_at=payment.released_at,
        action=checkout.action if checkout else None,
        instructions=checkout.instructions if checkout else None,
    )


def _buyers_order(db: Db, principal: Principal, order_id: str) -> Order:
    order = order_service.get_order(db, order_id)
    if order.buyer_user_id != principal.user_id:
        raise NotFound("That order does not exist.")
    return order


@router.post(
    "/orders/{order_id}/payment",
    response_model=PaymentOut,
    operation_id="orders_start_payment",
)
def start_payment(order_id: str, principal: CurrentPrincipal, db: Db) -> PaymentOut:
    """Begin paying, or return the attempt already open."""
    order = _buyers_order(db, principal, order_id)
    payment = payment_service.ensure_payment(db, order)
    db.commit()
    return payment_out(payment, order)


@router.post(
    "/orders/{order_id}/payment/sandbox-complete",
    response_model=PaymentOut,
    operation_id="orders_complete_sandbox_payment",
)
def complete_sandbox_payment(
    order_id: str, body: SandboxOutcomeIn, principal: CurrentPrincipal, db: Db
) -> PaymentOut:
    """Play the wallet's part in development. Refused in production."""
    order = _buyers_order(db, principal, order_id)
    payment = payment_service.complete_sandbox_payment(db, order=order, outcome=body.outcome)
    db.commit()
    return payment_out(payment, order)


@router.post(
    "/orders/{order_id}/payment/bank-reference",
    response_model=PaymentOut,
    operation_id="orders_submit_bank_reference",
)
def submit_bank_reference(
    order_id: str, body: BankReferenceIn, principal: CurrentPrincipal, db: Db
) -> PaymentOut:
    order = _buyers_order(db, principal, order_id)
    payment = payment_service.submit_bank_reference(db, order=order, reference=body.reference)
    db.commit()
    return payment_out(payment, order)


@router.post("/payments/webhooks/{provider}", operation_id="payments_provider_callback")
async def provider_callback(
    provider: str,
    request: Request,
    db: Db,
    x_sandbox_signature: str | None = Header(default=None),
) -> dict[str, bool]:
    """Receive a provider event. A repeated event is accepted and ignored."""
    payment_service.ingest_callback(
        db,
        provider_name=provider,
        body=await request.body(),
        signature=x_sandbox_signature,
    )
    db.commit()
    return {"received": True}
