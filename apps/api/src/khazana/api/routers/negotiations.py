"""Bargaining with the bot, and the brand's switches for both value band agents.

The buyer's view of a negotiation never contains the floor, the step, or what
the model proposed before the clamp. The brand's view contains all three.
"""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from ...core.errors import NotFound
from ...core.tenancy import assert_owns
from ...models import AuditLog, Lot, Negotiation, User
from ...models.enums import ChatRole, NegotiationStatus, PaymentMethod
from ...services import audit_service, bargaining_service, markdown_service
from ...services.order_service import Delivery
from ..deps import AdminOnly, CurrentBrand, CurrentPrincipal, Db, Principal, client_ip

router = APIRouter(tags=["bargaining"])


class StartIn(BaseModel):
    lot_id: str
    message: str = Field(default="", max_length=1_000)
    offer_pkr: int | None = Field(default=None, ge=1)


class TurnIn(BaseModel):
    message: str = Field(default="", max_length=1_000)
    offer_pkr: int | None = Field(default=None, ge=1)


class OrderIn(BaseModel):
    delivery_address: str = Field(min_length=5, max_length=500)
    delivery_phone: str = Field(min_length=10, max_length=14)
    payment_method: PaymentMethod


class MessageOut(BaseModel):
    role: ChatRole
    body: str
    offer_pkr: int | None
    created_at: datetime


class NegotiationOut(BaseModel):
    id: str
    lot_id: str
    lot_code: str
    status: NegotiationStatus
    pieces: int
    list_price_pkr: int
    asking_price_pkr: int
    agreed_price_pkr: int | None
    agreed_until: datetime | None
    rounds: int
    order_id: str | None
    messages: list[MessageOut]


class BrandMessageOut(MessageOut):
    proposed_pkr: int | None
    clamped: bool


class BrandNegotiationOut(BaseModel):
    id: str
    lot_code: str
    status: NegotiationStatus
    pieces: int
    list_price_pkr: int
    floor_price_pkr: int
    step_pkr: int
    asking_price_pkr: int
    agreed_price_pkr: int | None
    rounds: int
    messages: list[BrandMessageOut]


class AgentsIn(BaseModel):
    """Send a field to change it. null means inherit the brand's setting."""

    bargaining_enabled: bool | None = None
    auto_markdown_enabled: bool | None = None


class AgentsOut(BaseModel):
    lot_id: str
    bargaining_enabled: bool | None
    auto_markdown_enabled: bool | None


def _user(db: Session, principal: Principal) -> User:
    user = db.get(User, principal.user_id)
    if user is None:
        raise NotFound("That account no longer exists.")
    return user


def _out(db: Session, negotiation: Negotiation) -> NegotiationOut:
    lot = db.get(Lot, negotiation.lot_id)
    return NegotiationOut(
        id=negotiation.id,
        lot_id=negotiation.lot_id,
        lot_code=lot.lot_code if lot else "",
        status=negotiation.status,
        pieces=negotiation.pieces,
        list_price_pkr=negotiation.list_price_pkr,
        asking_price_pkr=negotiation.asking_price_pkr,
        agreed_price_pkr=negotiation.agreed_price_pkr,
        agreed_until=negotiation.agreed_until,
        rounds=negotiation.rounds,
        order_id=negotiation.order_id,
        messages=[
            MessageOut(role=m.role, body=m.body, offer_pkr=m.offer_pkr, created_at=m.created_at)
            for m in negotiation.messages
        ],
    )


@router.post(
    "/negotiations",
    response_model=NegotiationOut,
    status_code=status.HTTP_201_CREATED,
    operation_id="negotiations_start",
    responses={409: {"description": "The lot is not open to bargaining"}},
)
def start(body: StartIn, principal: CurrentPrincipal, db: Db) -> NegotiationOut:
    """Start bargaining over a whole lot whose brand allows it."""
    negotiation = bargaining_service.start(
        db,
        buyer=_user(db, principal),
        lot_id=body.lot_id,
        message=body.message,
        offer=body.offer_pkr,
    )
    db.commit()
    return _out(db, negotiation)


@router.get(
    "/negotiations/{negotiation_id}",
    response_model=NegotiationOut,
    operation_id="negotiations_detail",
)
def detail(negotiation_id: str, principal: CurrentPrincipal, db: Db) -> NegotiationOut:
    negotiation = bargaining_service.get_for_buyer(
        db, buyer=_user(db, principal), negotiation_id=negotiation_id
    )
    db.commit()
    return _out(db, negotiation)


@router.post(
    "/negotiations/{negotiation_id}/messages",
    response_model=NegotiationOut,
    operation_id="negotiations_reply",
)
def reply(negotiation_id: str, body: TurnIn, principal: CurrentPrincipal, db: Db) -> NegotiationOut:
    buyer = _user(db, principal)
    negotiation = bargaining_service.get_for_buyer(db, buyer=buyer, negotiation_id=negotiation_id)
    bargaining_service.respond(
        db, buyer=buyer, negotiation=negotiation, message=body.message, offer=body.offer_pkr
    )
    db.commit()
    return _out(db, negotiation)


@router.post(
    "/negotiations/{negotiation_id}/accept",
    response_model=NegotiationOut,
    operation_id="negotiations_accept",
)
def accept(negotiation_id: str, principal: CurrentPrincipal, db: Db) -> NegotiationOut:
    """Take the current asking price. It is held for 48 hours."""
    negotiation = bargaining_service.accept(
        db, buyer=_user(db, principal), negotiation_id=negotiation_id
    )
    db.commit()
    return _out(db, negotiation)


@router.post(
    "/negotiations/{negotiation_id}/order",
    response_model=NegotiationOut,
    operation_id="negotiations_order",
)
def order(
    negotiation_id: str, body: OrderIn, request: Request, principal: CurrentPrincipal, db: Db
) -> NegotiationOut:
    """Order the whole lot at the agreed price."""
    buyer = _user(db, principal)
    bargaining_service.order(
        db,
        buyer=buyer,
        negotiation_id=negotiation_id,
        delivery=Delivery(
            city=buyer.reseller_profile.city if buyer.reseller_profile else "",
            address=body.delivery_address,
            phone=body.delivery_phone,
        ),
        method=body.payment_method,
        ip=client_ip(request),
    )
    db.commit()
    return _out(
        db, bargaining_service.get_for_buyer(db, buyer=buyer, negotiation_id=negotiation_id)
    )


@router.get(
    "/brands/{brand_id}/negotiations",
    response_model=list[BrandNegotiationOut],
    operation_id="brand_negotiations",
)
def brand_negotiations(brand_id: str, principal: CurrentBrand, db: Db) -> list[BrandNegotiationOut]:
    """Every negotiation on this brand's lots, with each clamp the code applied."""
    assert_owns(principal, brand_id)
    rows = db.scalars(
        select(Negotiation)
        .where(Negotiation.brand_id == brand_id)
        .order_by(Negotiation.created_at.desc())
        .limit(100)
    )
    out = []
    for negotiation in rows:
        lot = db.get(Lot, negotiation.lot_id)
        out.append(
            BrandNegotiationOut(
                id=negotiation.id,
                lot_code=lot.lot_code if lot else "",
                status=negotiation.status,
                pieces=negotiation.pieces,
                list_price_pkr=negotiation.list_price_pkr,
                floor_price_pkr=negotiation.floor_price_pkr,
                step_pkr=negotiation.step_pkr,
                asking_price_pkr=negotiation.asking_price_pkr,
                agreed_price_pkr=negotiation.agreed_price_pkr,
                rounds=negotiation.rounds,
                messages=[
                    BrandMessageOut(
                        role=m.role,
                        body=m.body,
                        offer_pkr=m.offer_pkr,
                        created_at=m.created_at,
                        proposed_pkr=m.proposed_pkr,
                        clamped=m.clamped,
                    )
                    for m in negotiation.messages
                ],
            )
        )
    return out


@router.patch(
    "/lots/{lot_id}/agents",
    response_model=AgentsOut,
    operation_id="lots_set_agents",
    responses={404: {"description": "No such lot, or it belongs to another brand"}},
)
def set_agents(lot_id: str, body: AgentsIn, principal: CurrentBrand, db: Db) -> AgentsOut:
    """Turn the bargaining bot or the markdown agent on or off for one lot.

    Only the fields sent are changed. Sending null returns that lot to the
    brand's own setting.
    """
    lot = db.get(Lot, lot_id)
    if lot is None:
        raise NotFound("That lot does not exist.")
    assert_owns(principal, lot.brand_id)
    before = {
        "bargaining_enabled": lot.bargaining_enabled,
        "auto_markdown_enabled": lot.auto_markdown_enabled,
    }
    for field in body.model_fields_set:
        setattr(lot, field, getattr(body, field))
    db.flush()
    audit_service.record(
        db,
        action="lot.agents_changed",
        entity_type="lot",
        entity_id=lot.id,
        brand_id=lot.brand_id,
        actor_user_id=principal.user_id,
        actor_role=principal.role,
        before=before,
        after={
            "bargaining_enabled": lot.bargaining_enabled,
            "auto_markdown_enabled": lot.auto_markdown_enabled,
        },
    )
    db.commit()
    return AgentsOut(
        lot_id=lot.id,
        bargaining_enabled=lot.bargaining_enabled,
        auto_markdown_enabled=lot.auto_markdown_enabled,
    )


class PriceMoveOut(BaseModel):
    at: datetime
    action: str
    by: str
    before: dict[str, object] | None
    after: dict[str, object] | None
    note: str | None


@router.get(
    "/lots/{lot_id}/price-history",
    response_model=list[PriceMoveOut],
    operation_id="lots_price_history",
    responses={404: {"description": "No such lot, or it belongs to another brand"}},
)
def price_history(lot_id: str, principal: CurrentBrand, db: Db) -> list[PriceMoveOut]:
    """Every automatic markdown and agent switch on this lot, newest first."""
    lot = db.get(Lot, lot_id)
    if lot is None:
        raise NotFound("That lot does not exist.")
    assert_owns(principal, lot.brand_id)
    rows = db.scalars(
        select(AuditLog)
        .where(
            AuditLog.entity_id == lot.id,
            AuditLog.action.in_(["lot.marked_down", "lot.agents_changed"]),
        )
        .order_by(AuditLog.created_at.desc())
    )
    return [
        PriceMoveOut(
            at=row.created_at,
            action=row.action,
            by=row.actor_kind,
            before=row.before,
            after=row.after,
            note=row.note,
        )
        for row in rows
    ]


class MarkdownRunOut(BaseModel):
    lot_code: str
    before_percent: float
    after_percent: float
    proposed_percent: float
    reason: str


@router.post(
    "/admin/jobs/markdowns",
    response_model=list[MarkdownRunOut],
    operation_id="admin_run_markdowns",
)
def run_markdowns(_: AdminOnly, db: Db) -> list[MarkdownRunOut]:
    """Run the markdown agent now, live, at the full price.

    For a decision someone wants to see straight away. The daily schedule
    uses the batch endpoints below instead.
    """
    results = markdown_service.run(db)
    db.commit()
    return _markdown_out(results)


@router.post(
    "/admin/jobs/markdowns/batch",
    response_model=list[MarkdownRunOut],
    operation_id="admin_submit_markdown_batch",
)
def submit_markdown_batch(_: AdminOnly, db: Db) -> list[MarkdownRunOut]:
    """Send today's markdown decisions as one batch, at half the price.

    Daily, from the scheduler. Returns nothing until the batch comes back,
    except offline, where the batch answers at once.
    """
    return _markdown_out(markdown_service.submit_batch(db))


@router.post(
    "/admin/jobs/markdowns/collect",
    response_model=list[MarkdownRunOut],
    operation_id="admin_collect_markdown_batch",
)
def collect_markdown_batch(_: AdminOnly, db: Db) -> list[MarkdownRunOut]:
    """Apply every markdown decision whose batch has ended. Every half hour."""
    return _markdown_out(markdown_service.collect_batch(db))


def _markdown_out(results: list[markdown_service.MarkdownResult]) -> list[MarkdownRunOut]:
    return [
        MarkdownRunOut(
            lot_code=r.lot_code,
            before_percent=r.before_percent,
            after_percent=r.after_percent,
            proposed_percent=r.proposed_percent,
            reason=r.reason,
        )
        for r in results
    ]
