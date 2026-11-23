"""Request dependencies: who is calling, and what they are allowed to touch."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Annotated

from fastapi import Depends, Header, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..core.errors import Forbidden, Unauthenticated
from ..core.security import TokenError, decode_access_token
from ..core.tenancy import set_session_tenant
from ..db import get_db
from ..models import BrandMember, User
from ..models.enums import UserRole
from ..services.auth_service import token_still_valid


@dataclass(slots=True)
class Principal:
    """The authenticated caller, resolved once per request."""

    user_id: str
    role: UserRole
    brand_ids: list[str] = field(default_factory=list)

    @property
    def is_admin(self) -> bool:
        return self.role == UserRole.ADMIN


def get_principal(
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    authorization: Annotated[str | None, Header()] = None,
) -> Principal:
    """Authenticate the bearer token and set the tenant for this transaction.

    Brand memberships are re read from the database rather than trusted from
    the token. A token minted before a membership was revoked must not keep
    working, and the cost of one indexed lookup per request is not worth the
    risk of getting that wrong.
    """
    if not authorization or not authorization.lower().startswith("bearer "):
        raise Unauthenticated("Sign in to continue.").as_http()

    token = authorization.split(" ", 1)[1].strip()
    try:
        payload = decode_access_token(token)
    except TokenError:
        raise Unauthenticated("Your session has expired. Sign in again.").as_http() from None

    user = db.get(User, str(payload.get("sub")))
    if user is None or not user.is_active or user.is_deleted:
        raise Forbidden("This account is not active.").as_http()
    if not token_still_valid(user, payload):
        raise Unauthenticated("You were signed out. Sign in again.").as_http()

    brand_ids = list(
        db.scalars(select(BrandMember.brand_id).where(BrandMember.user_id == user.id)).all()
    )
    principal = Principal(user_id=user.id, role=user.role, brand_ids=brand_ids)

    set_session_tenant(db, principal)
    request.state.principal = principal
    return principal


CurrentPrincipal = Annotated[Principal, Depends(get_principal)]
Db = Annotated[Session, Depends(get_db)]


def require_role(*allowed: UserRole) -> Callable[[Principal], Principal]:
    """Dependency factory for role gates.

    Usage:
        @router.get("/admin/queue", dependencies=[Depends(require_role(UserRole.ADMIN))])
    """

    def _check(principal: CurrentPrincipal) -> Principal:
        if principal.role not in allowed:
            raise Forbidden("You do not have access to this.").as_http()
        return principal

    return _check


def require_brand(principal: CurrentPrincipal) -> Principal:
    """A brand user who actually belongs to at least one brand."""
    if principal.role == UserRole.ADMIN:
        return principal
    if principal.role != UserRole.BRAND or not principal.brand_ids:
        raise Forbidden("This action is for verified brand accounts.").as_http()
    return principal


CurrentBrand = Annotated[Principal, Depends(require_brand)]
AdminOnly = Annotated[Principal, Depends(require_role(UserRole.ADMIN))]


def client_ip(request: Request) -> str | None:
    """The caller's address, as far as it can be trusted.

    ``X-Forwarded-For`` is written by whoever sends the request, so its first
    entry is whatever a client chose to put there. Each trusted proxy appends
    the address it received the request from, so with ``trusted_proxy_count``
    proxies in front, the real client is that many entries from the right.
    With none configured the header is ignored entirely: otherwise one script
    could claim a new address on every request and walk straight past the
    per address limits.
    """
    proxies = get_settings().trusted_proxy_count
    direct = request.client.host if request.client else None
    if proxies == 0:
        return direct
    hops = [part.strip() for part in request.headers.get("x-forwarded-for", "").split(",")]
    hops = [hop for hop in hops if hop]
    if len(hops) < proxies:
        return direct
    return hops[-proxies][:45]
