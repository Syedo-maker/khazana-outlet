"""Committee pools for resellers. Members are never identified to each other."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import APIRouter, Request, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ...config import get_settings
from ...core.errors import NotFound
from ...models import Lot, Pool, User
from ...models.enums import PaymentMethod, PoolStatus
from ...services import pool_service
from ..deps import CurrentPrincipal, Db, Principal, client_ip
from .catalog import BrowseItemOut, _browse_item

router = APIRouter(prefix="/pools", tags=["pools"])


class LineIn(BaseModel):
    size: str = Field(min_length=1, max_length=32)
    color: str = Field(min_length=1, max_length=48)
    pieces: int = Field(ge=1, le=100_000)


class MembershipIn(BaseModel):
    lines: list[LineIn] = Field(min_length=1, max_length=60)
    delivery_address: str = Field(min_length=5, max_length=500)
    delivery_phone: str = Field(min_length=10, max_length=14)
    payment_method: PaymentMethod


class OpenPoolIn(MembershipIn):
    lot_id: str


class LineOut(BaseModel):
    size: str
    color: str
    pieces: int


class MineOut(BaseModel):
    requested: list[LineOut]
    allocated: list[LineOut] | None
    order_id: str | None
    is_organiser: bool


class PoolOut(BaseModel):
    id: str
    item: BrowseItemOut
    city: str
    status: PoolStatus
    closes_at: datetime
    members: int
    min_members: int
    places_left: int
    pieces_covered: int
    meets_minimum: bool
    shortfall: list[str]
    uncovered: list[LineOut]
    mine: MineOut | None


class PlacedOut(BaseModel):
    order_ids: list[str]


def _user(db: Session, principal: Principal) -> User:
    user = db.get(User, principal.user_id)
    if user is None:
        raise NotFound("That account no longer exists.")
    return user


def _lines(raw: dict[str, Any] | None) -> list[LineOut]:
    return [LineOut(**line) for line in (raw or {}).get("lines", [])]


def _out(db: Session, principal: Principal, pool: Pool) -> PoolOut:
    lot = db.get(Lot, pool.lot_id)
    if lot is None:
        raise NotFound("That lot no longer exists.")
    result = pool_service.coverage(db, pool, lot)
    settings = get_settings()
    member = next((m for m in pool.members if m.user_id == principal.user_id), None)
    mine = None
    if member is not None:
        allocated = member.allocated or {
            "lines": [_line_json(x) for x in result.allocation.get(member.id, [])]
        }
        mine = MineOut(
            requested=_lines(member.requested),
            allocated=_lines(allocated),
            order_id=member.order_id,
            is_organiser=pool.organiser_user_id == principal.user_id,
        )
    return PoolOut(
        id=pool.id,
        item=_browse_item(db, principal, lot),
        city=pool.city,
        status=pool.status,
        closes_at=pool.closes_at,
        members=result.members,
        min_members=settings.pool_min_members,
        places_left=max(0, settings.pool_max_members - result.members),
        pieces_covered=result.pieces,
        meets_minimum=result.meets_minimum,
        shortfall=result.shortfall,
        uncovered=[
            LineOut(size=size, color=color, pieces=pieces)
            for (size, color), pieces in sorted(result.uncovered.items())
        ],
        mine=mine,
    )


def _line_json(line: Any) -> dict[str, Any]:
    return {"size": line.size, "color": line.color, "pieces": line.pieces}


@router.get("", response_model=list[PoolOut], operation_id="pools_open_in_my_city")
def open_pools(principal: CurrentPrincipal, db: Db) -> list[PoolOut]:
    """Open pools in the caller's own city, soonest closing first."""
    user = _user(db, principal)
    return [_out(db, principal, pool) for pool in pool_service.open_pools_for(db, user)]


@router.post(
    "",
    response_model=PoolOut,
    status_code=status.HTTP_201_CREATED,
    operation_id="pools_open",
)
def open_pool(body: OpenPoolIn, principal: CurrentPrincipal, db: Db) -> PoolOut:
    """Start a pool on a lot, with the caller as its first member and organiser."""
    pool = pool_service.open_pool(
        db,
        organiser=_user(db, principal),
        lot_id=body.lot_id,
        lines=[line.model_dump() for line in body.lines],
        address=body.delivery_address,
        phone=body.delivery_phone,
        method=body.payment_method,
    )
    db.commit()
    return _out(db, principal, pool)


@router.get("/{pool_id}", response_model=PoolOut, operation_id="pools_detail")
def pool_detail(pool_id: str, principal: CurrentPrincipal, db: Db) -> PoolOut:
    pool = pool_service.get_pool(db, pool_id)
    user = _user(db, principal)
    is_member = any(m.user_id == user.id for m in pool.members)
    city = user.reseller_profile.city if user.reseller_profile else ""
    if not is_member and city.strip().lower() != pool.city.lower():
        raise NotFound("That pool does not exist.")
    return _out(db, principal, pool)


@router.post("/{pool_id}/join", response_model=PoolOut, operation_id="pools_join")
def join_pool(pool_id: str, body: MembershipIn, principal: CurrentPrincipal, db: Db) -> PoolOut:
    pool = pool_service.join(
        db,
        user=_user(db, principal),
        pool_id=pool_id,
        lines=[line.model_dump() for line in body.lines],
        address=body.delivery_address,
        phone=body.delivery_phone,
        method=body.payment_method,
    )
    db.commit()
    return _out(db, principal, pool)


@router.post("/{pool_id}/leave", response_model=PoolOut, operation_id="pools_leave")
def leave_pool(pool_id: str, principal: CurrentPrincipal, db: Db) -> PoolOut:
    pool = pool_service.leave(db, user=_user(db, principal), pool_id=pool_id)
    db.commit()
    return _out(db, principal, pool)


@router.post("/{pool_id}/place", response_model=PlacedOut, operation_id="pools_place")
def place_pool(pool_id: str, request: Request, principal: CurrentPrincipal, db: Db) -> PlacedOut:
    """Create every member's order together. Organiser only."""
    orders = pool_service.place(
        db, actor=_user(db, principal), pool_id=pool_id, ip=client_ip(request)
    )
    db.commit()
    return PlacedOut(order_ids=[order.id for order in orders])
