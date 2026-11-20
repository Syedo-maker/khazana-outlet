"""Committee pools: three or four resellers in one city buying a lot together.

How a pool works:

1. A verified reseller opens a pool on a lot whose brand allows pooled
   orders, saying which sizes and colours they want. They are the organiser.
2. Other verified resellers in the same city find it under open pools and
   join with their own sizes and colours. Members see how many places are
   taken and what is still uncovered, never who the others are.
3. When enough members have joined, the organiser places the pool. The lot
   is split by need: where requests for a size and colour exceed the stock,
   each member gets a share in proportion to what they asked for.
4. Each member gets their own ordinary order, with their own delivery and
   payment, all created together or not at all.

The brand's rules hold for the pool as a whole: together the members must
meet the lot's minimum order and the brand's minimum order value. Below that,
nothing is placed.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..core.errors import Conflict, Forbidden, NotFound, ValidationFailed
from ..models import BrandPolicy, Lot, Order, Pool, PoolMember, User, utcnow
from ..models.enums import PaymentMethod, PoolStatus
from . import order_service
from .order_service import Delivery, LineChoice, Purchase

Key = tuple[str, str]


@dataclass(slots=True)
class Coverage:
    available: dict[Key, int]
    requested: dict[Key, int]
    allocation: dict[str, list[LineChoice]]
    pieces: int
    members: int
    meets_minimum: bool
    shortfall: list[str] = field(default_factory=list)

    @property
    def uncovered(self) -> dict[Key, int]:
        return {
            key: left
            for key, stock in self.available.items()
            if (left := stock - min(stock, self.requested.get(key, 0))) > 0
        }


def _lines(raw: list[dict[str, Any]] | list[LineChoice]) -> list[LineChoice]:
    lines = [
        line
        if isinstance(line, LineChoice)
        else LineChoice(
            size=str(line["size"]), color=str(line["color"]), pieces=int(line["pieces"])
        )
        for line in raw
    ]
    seen: set[Key] = set()
    for line in lines:
        if line.pieces < 1:
            raise ValidationFailed("Each size and colour needs at least 1 piece.")
        if (line.size, line.color) in seen:
            raise ValidationFailed(f"{line.size} {line.color} is listed twice.")
        seen.add((line.size, line.color))
    if not lines:
        raise ValidationFailed("Choose at least one size and colour.")
    return lines


def _as_json(lines: list[LineChoice]) -> dict[str, Any]:
    return {"lines": [{"size": x.size, "color": x.color, "pieces": x.pieces} for x in lines]}


@dataclass(slots=True)
class _Share:
    pieces: int
    remainder: float
    position: int
    member_id: str


def allocate(
    available: dict[Key, int], requests: list[tuple[str, list[LineChoice]]]
) -> dict[str, list[LineChoice]]:
    """Split stock by need.

    Where everyone's requests for a size and colour fit, everyone gets what
    they asked for. Where they do not, each member gets a share in proportion
    to their request, rounded down, and the leftover pieces go one at a time
    to the largest remainders, earlier members first on a tie.
    """
    wanted: dict[Key, list[tuple[int, str, int]]] = defaultdict(list)
    for position, (member_id, lines) in enumerate(requests):
        for line in lines:
            wanted[(line.size, line.color)].append((position, member_id, line.pieces))

    given: dict[str, dict[Key, int]] = defaultdict(dict)
    for key, asks in wanted.items():
        stock = available.get(key, 0)
        total = sum(pieces for _, _, pieces in asks)
        if total <= stock:
            for _, member_id, pieces in asks:
                given[member_id][key] = pieces
            continue
        shares = [
            _Share(
                pieces=int(stock * pieces / total),
                remainder=stock * pieces / total - int(stock * pieces / total),
                position=position,
                member_id=member_id,
            )
            for position, member_id, pieces in asks
        ]
        leftover = stock - sum(share.pieces for share in shares)
        for share in sorted(shares, key=lambda item: (-item.remainder, item.position))[:leftover]:
            share.pieces += 1
        for share in shares:
            if share.pieces:
                given[share.member_id][key] = share.pieces

    return {
        member_id: [
            LineChoice(size=size, color=color, pieces=pieces)
            for (size, color), pieces in sorted(given.get(member_id, {}).items())
        ]
        for member_id, _ in requests
    }


def _policy(db: Session, lot: Lot) -> BrandPolicy:
    policy = db.scalar(select(BrandPolicy).where(BrandPolicy.brand_id == lot.brand_id))
    if policy is None or not policy.allow_pooled_orders:
        raise Conflict("This brand does not allow pooled orders on its lots.")
    return policy


def _city(user: User) -> str:
    profile = user.reseller_profile
    if profile is None:
        raise Forbidden("Pools are for reseller accounts.")
    return profile.city.strip()


def _validate_request(db: Session, lot: Lot, lines: list[LineChoice]) -> None:
    stock = {(x.size, x.color): x.pieces for x in order_service.available_lines(db, lot)}
    for line in lines:
        if (line.size, line.color) not in stock:
            raise ValidationFailed(f"This lot has no {line.size} {line.color} left.")


def coverage(db: Session, pool: Pool, lot: Lot) -> Coverage:
    available = {(x.size, x.color): x.pieces for x in order_service.available_lines(db, lot)}
    requests = [(m.id, _lines(m.requested["lines"])) for m in pool.members]
    requested: dict[Key, int] = defaultdict(int)
    for _, lines in requests:
        for line in lines:
            requested[(line.size, line.color)] += line.pieces
    allocation = allocate(available, requests)
    pieces = sum(x.pieces for lines in allocation.values() for x in lines)

    shortfall = []
    settings = get_settings()
    if len(pool.members) < settings.pool_min_members:
        shortfall.append(f"{settings.pool_min_members - len(pool.members)} more member(s) needed.")
    takes_all = pieces == lot.available_pieces
    if pieces < lot.min_order_pieces and not takes_all:
        shortfall.append(f"Together the pool needs {lot.min_order_pieces} pieces; it has {pieces}.")
    policy = db.scalar(select(BrandPolicy).where(BrandPolicy.brand_id == lot.brand_id))
    unit = -(-lot.lot_price_pkr // lot.total_pieces)
    if policy and pieces * unit < policy.min_lot_value_pkr and not takes_all:
        shortfall.append(
            f"Together the pool needs an order value of {policy.min_lot_value_pkr:,} PKR."
        )
    return Coverage(
        available=available,
        requested=dict(requested),
        allocation=allocation,
        pieces=pieces,
        members=len(pool.members),
        meets_minimum=not shortfall,
        shortfall=shortfall,
    )


def get_pool(db: Session, pool_id: str) -> Pool:
    pool = db.get(Pool, pool_id)
    if pool is None:
        raise NotFound("That pool does not exist.")
    return pool


def _open(pool: Pool) -> None:
    closes = pool.closes_at if pool.closes_at.tzinfo else pool.closes_at.replace(tzinfo=UTC)
    if PoolStatus(pool.status) != PoolStatus.OPEN or closes <= utcnow():
        raise Conflict("This pool is no longer open.")


def open_pool(
    db: Session,
    *,
    organiser: User,
    lot_id: str,
    lines: list[Any],
    address: str,
    phone: str,
    method: PaymentMethod,
) -> Pool:
    order_service.require_buyer(db, organiser)
    city = _city(organiser)
    lot = order_service.buyable_lot(db, lot_id=lot_id, city=city)
    _policy(db, lot)
    chosen = _lines(lines)
    _validate_request(db, lot, chosen)

    pool = Pool(
        lot_id=lot.id,
        organiser_user_id=organiser.id,
        city=city,
        status=PoolStatus.OPEN,
        closes_at=utcnow() + timedelta(days=get_settings().pool_open_days),
    )
    db.add(pool)
    db.flush()
    db.add(
        PoolMember(
            pool_id=pool.id,
            user_id=organiser.id,
            requested=_as_json(chosen),
            delivery_address=address.strip(),
            delivery_phone=phone.strip(),
            payment_method=method,
        )
    )
    db.flush()
    db.refresh(pool)
    return pool


def join(
    db: Session,
    *,
    user: User,
    pool_id: str,
    lines: list[Any],
    address: str,
    phone: str,
    method: PaymentMethod,
) -> Pool:
    order_service.require_buyer(db, user)
    pool = get_pool(db, pool_id)
    _open(pool)
    if _city(user).lower() != pool.city.lower():
        raise Forbidden(f"This pool is for resellers in {pool.city}.")
    if any(member.user_id == user.id for member in pool.members):
        raise Conflict("You are already in this pool.")
    if len(pool.members) >= get_settings().pool_max_members:
        raise Conflict("This pool is full.")
    lot = order_service.buyable_lot(db, lot_id=pool.lot_id, city=pool.city)
    chosen = _lines(lines)
    _validate_request(db, lot, chosen)
    db.add(
        PoolMember(
            pool_id=pool.id,
            user_id=user.id,
            requested=_as_json(chosen),
            delivery_address=address.strip(),
            delivery_phone=phone.strip(),
            payment_method=method,
        )
    )
    db.flush()
    db.refresh(pool)
    return pool


def leave(db: Session, *, user: User, pool_id: str) -> Pool:
    pool = get_pool(db, pool_id)
    _open(pool)
    member = next((m for m in pool.members if m.user_id == user.id), None)
    if member is None:
        raise NotFound("You are not in this pool.")
    pool.members.remove(member)
    db.flush()
    if not pool.members:
        pool.status = PoolStatus.CANCELLED
    elif pool.organiser_user_id == user.id:
        # The longest standing member organises from here.
        pool.organiser_user_id = pool.members[0].user_id
    db.flush()
    return pool


def place(db: Session, *, actor: User, pool_id: str, ip: str | None = None) -> list[Order]:
    """Create every member's order together, or none of them."""
    pool = get_pool(db, pool_id)
    _open(pool)
    if pool.organiser_user_id != actor.id:
        raise Forbidden("Only the pool's organiser can place it.")
    lot = order_service.buyable_lot(db, lot_id=pool.lot_id, city=pool.city, lock=True)
    policy = _policy(db, lot)
    result = coverage(db, pool, lot)
    if not result.meets_minimum:
        raise Conflict("The pool cannot be placed yet. " + " ".join(result.shortfall))

    orders = []
    for member in pool.members:
        lines = result.allocation.get(member.id, [])
        if not lines:
            continue
        buyer = db.get(User, member.user_id)
        if buyer is None:
            continue
        order_service.require_buyer(db, buyer)
        method = PaymentMethod(member.payment_method)
        if method == PaymentMethod.COD and not policy.allow_cod:
            raise ValidationFailed(f"Cash on delivery is not available for {lot.lot_code}.")
        pricing = order_service.price_purchase(
            db,
            lot=lot,
            purchase=Purchase(lot_id=lot.id, whole_lot=False, lines=tuple(lines)),
            destination_city=pool.city,
            pooled=True,
        )
        order = order_service.create_order(
            db,
            buyer=buyer,
            lot=lot,
            pricing=pricing,
            delivery=Delivery(
                city=pool.city, address=member.delivery_address, phone=member.delivery_phone
            ),
            method=method,
            ip=ip,
        )
        member.allocated = _as_json(lines)
        member.order_id = order.id
        orders.append(order)

    pool.status = PoolStatus.ORDERED
    pool.ordered_at = utcnow()
    db.flush()
    return orders


def open_pools_for(db: Session, user: User) -> list[Pool]:
    """Open pools in the user's own city, soonest closing first."""
    city = _city(user)
    now = utcnow()
    pools = db.scalars(
        select(Pool)
        .where(Pool.status == PoolStatus.OPEN, Pool.city.ilike(city))
        .order_by(Pool.closes_at)
    ).all()
    return [
        p
        for p in pools
        if (p.closes_at if p.closes_at.tzinfo else p.closes_at.replace(tzinfo=UTC)) > now
    ]


def expire_pools(db: Session, *, now: datetime | None = None) -> int:
    """Close pools whose time ran out. Run on a schedule."""
    moment = now or utcnow()
    expired = 0
    for pool in db.scalars(select(Pool).where(Pool.status == PoolStatus.OPEN)):
        closes = pool.closes_at if pool.closes_at.tzinfo else pool.closes_at.replace(tzinfo=UTC)
        if closes <= moment:
            pool.status = PoolStatus.EXPIRED
            expired += 1
    db.flush()
    return expired
