"""The upcycle and donation route: matches for brands, coordination for admins.

Brands see a partner's name, kind and city. Contact details stay with the
administrators who arrange each handover.
"""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from ...core.errors import NotFound, ValidationFailed
from ...core.tenancy import assert_owns
from ...models import Lot, Partner, Redirection, User
from ...models.enums import RedirectStatus
from ...services import audit_service, redirect_service
from ..deps import AdminOnly, CurrentBrand, Db, Principal

router = APIRouter(tags=["redirections"])


class MatchOut(BaseModel):
    partner_id: str
    name: str
    kind: str
    city: str
    score: int
    reasons: list[str]


class ProposeIn(BaseModel):
    partner_id: str
    route: str = Field(pattern="^(donation|upcycle_sale)$")
    price_pkr: int = Field(default=0, ge=0)
    note: str = Field(default="", max_length=500)


class RedirectionOut(BaseModel):
    id: str
    lot_id: str
    partner_name: str
    partner_kind: str
    partner_city: str
    route: str
    pieces: int
    price_pkr: int
    status: RedirectStatus
    collected_at: datetime | None


class PartnerIn(BaseModel):
    name: str = Field(min_length=2, max_length=160)
    kind: str = Field(pattern="^(tailor|artisan|ngo|recycler)$")
    city: str = Field(min_length=2, max_length=80)
    category_words: list[str] = Field(default_factory=list, max_length=20)
    grades: list[str] = Field(default_factory=list, max_length=3)
    min_pieces: int = Field(default=1, ge=1)
    max_pieces: int | None = Field(default=None, ge=1)
    contact_name: str = Field(default="", max_length=120)
    contact_phone: str = Field(default="", max_length=20)
    is_active: bool = True


class PartnerOut(PartnerIn):
    id: str


class StatusIn(BaseModel):
    status: RedirectStatus


def _user(db: Session, principal: Principal) -> User:
    user = db.get(User, principal.user_id)
    if user is None:
        raise NotFound("That account no longer exists.")
    return user


def _owned_lot(db: Session, principal: Principal, lot_id: str) -> Lot:
    lot = db.get(Lot, lot_id)
    if lot is None:
        raise NotFound("That lot does not exist.")
    assert_owns(principal, lot.brand_id)
    return lot


def _redirection_out(db: Session, row: Redirection) -> RedirectionOut:
    partner = db.get(Partner, row.partner_id)
    return RedirectionOut(
        id=row.id,
        lot_id=row.lot_id,
        partner_name=partner.name if partner else "",
        partner_kind=partner.kind if partner else "",
        partner_city=partner.city if partner else "",
        route=row.route,
        pieces=row.pieces,
        price_pkr=row.price_pkr,
        status=row.status,
        collected_at=row.collected_at,
    )


def _partner_out(partner: Partner) -> PartnerOut:
    return PartnerOut(
        id=partner.id,
        name=partner.name,
        kind=partner.kind,
        city=partner.city,
        category_words=[str(w) for w in (partner.categories or {}).get("words", [])],
        grades=[str(g) for g in (partner.grades or {}).get("grades", [])],
        min_pieces=partner.min_pieces,
        max_pieces=partner.max_pieces,
        contact_name=partner.contact_name,
        contact_phone=partner.contact_phone,
        is_active=partner.is_active,
    )


@router.get(
    "/lots/{lot_id}/partner-matches",
    response_model=list[MatchOut],
    operation_id="lots_partner_matches",
)
def partner_matches(lot_id: str, principal: CurrentBrand, db: Db) -> list[MatchOut]:
    """Partners who could use this lot, best fit first, with the reasons."""
    lot = _owned_lot(db, principal, lot_id)
    return [
        MatchOut(
            partner_id=m.partner.id,
            name=m.partner.name,
            kind=m.partner.kind,
            city=m.partner.city,
            score=m.score,
            reasons=m.reasons,
        )
        for m in redirect_service.matches(db, lot)
    ]


@router.post(
    "/lots/{lot_id}/redirections",
    response_model=RedirectionOut,
    status_code=status.HTTP_201_CREATED,
    operation_id="lots_offer_to_partner",
)
def offer(lot_id: str, body: ProposeIn, principal: CurrentBrand, db: Db) -> RedirectionOut:
    """Offer the rest of this lot to a partner. Khazana Outlet arranges the handover."""
    lot = _owned_lot(db, principal, lot_id)
    row = redirect_service.propose(
        db,
        lot=lot,
        partner_id=body.partner_id,
        route=body.route,
        price_pkr=body.price_pkr,
        actor=_user(db, principal),
        note=body.note,
    )
    db.commit()
    return _redirection_out(db, row)


@router.get(
    "/brands/{brand_id}/redirections",
    response_model=list[RedirectionOut],
    operation_id="brand_redirections",
)
def brand_redirections(brand_id: str, principal: CurrentBrand, db: Db) -> list[RedirectionOut]:
    assert_owns(principal, brand_id)
    rows = db.scalars(
        select(Redirection)
        .where(Redirection.brand_id == brand_id)
        .order_by(Redirection.created_at.desc())
    )
    return [_redirection_out(db, row) for row in rows]


@router.get("/admin/partners", response_model=list[PartnerOut], operation_id="admin_partners")
def partners(_: AdminOnly, db: Db) -> list[PartnerOut]:
    return [_partner_out(p) for p in db.scalars(select(Partner).order_by(Partner.name))]


@router.post(
    "/admin/partners",
    response_model=PartnerOut,
    status_code=status.HTTP_201_CREATED,
    operation_id="admin_add_partner",
)
def add_partner(body: PartnerIn, principal: AdminOnly, db: Db) -> PartnerOut:
    if body.max_pieces is not None and body.max_pieces < body.min_pieces:
        raise ValidationFailed("The most pieces cannot be fewer than the least.")
    values = body.model_dump(exclude={"category_words", "grades"})
    partner = Partner(
        **values,
        categories={"words": body.category_words},
        grades={"grades": body.grades},
    )
    db.add(partner)
    db.flush()
    audit_service.record(
        db,
        action="partner.created",
        entity_type="partner",
        entity_id=partner.id,
        actor_user_id=principal.user_id,
        actor_role=principal.role,
        after={"name": body.name, "kind": body.kind, "city": body.city},
    )
    db.commit()
    return _partner_out(partner)


@router.get(
    "/admin/redirections", response_model=list[RedirectionOut], operation_id="admin_redirections"
)
def all_redirections(_: AdminOnly, db: Db) -> list[RedirectionOut]:
    rows = db.scalars(select(Redirection).order_by(Redirection.created_at.desc()).limit(200))
    return [_redirection_out(db, row) for row in rows]


@router.post(
    "/admin/redirections/{redirection_id}/status",
    response_model=RedirectionOut,
    operation_id="admin_redirection_status",
)
def set_status(redirection_id: str, body: StatusIn, principal: AdminOnly, db: Db) -> RedirectionOut:
    """Record that a partner accepted, collected, or that the offer fell through."""
    row = redirect_service.move(
        db, redirection_id=redirection_id, to=body.status, actor=_user(db, principal)
    )
    db.commit()
    return _redirection_out(db, row)
