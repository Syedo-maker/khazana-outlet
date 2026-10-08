"""Tenant scoping.

The single rule of this codebase: a query that touches a brand owned table
goes through ``scoped`` or it is a bug. The isolation test suite enumerates
``BRAND_SCOPED_TABLES`` and will fail if a new table is added without a
brand_id, and a review should reject any raw ``select(Lot)`` outside this
module's helpers.

Why a helper rather than trusting PostgreSQL row level security alone: the
policies in migration 0001 only apply when the application connects as a non
owner role, tests run on SQLite which has no row level security at all, and a
defence that is invisible in development is a defence nobody notices breaking.
Application scoping is the primary control, the policies are the backstop.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, TypeVar

from sqlalchemy import Select
from sqlalchemy.orm import Session

from ..models.enums import UserRole
from .errors import CrossTenant

if TYPE_CHECKING:
    from ..api.deps import Principal

T = TypeVar("T")


def scoped(statement: Select[Any], model: Any, principal: Principal) -> Select[Any]:
    """Restrict a select to what this principal may see.

    Admins see everything. A brand user sees only the brands they are a member
    of. A reseller sees nothing through this path: buyer facing visibility is a
    different question, answered by the catalogue service, because it depends
    on listing status and protection level rather than on ownership.
    """
    if principal.role == UserRole.ADMIN:
        return statement
    if principal.role == UserRole.BRAND:
        if not principal.brand_ids:
            # A brand user with no membership can see nothing. Returning an
            # impossible predicate is safer than returning the unfiltered
            # statement, which is what a missing check would do.
            return statement.where(model.brand_id.is_(None))
        return statement.where(model.brand_id.in_(principal.brand_ids))
    return statement.where(model.brand_id.is_(None))


def assert_owns(principal: Principal, brand_id: str | None) -> None:
    """Raise if this principal does not own the brand scoped record.

    Raises ``CrossTenant``, which is reported to the caller as a 404, so that
    probing identifiers tells an attacker nothing.
    """
    if principal.role == UserRole.ADMIN:
        return
    if brand_id is None or brand_id not in principal.brand_ids:
        raise CrossTenant("record not found")


def set_session_tenant(db: Session, principal: Principal) -> None:
    """Set the PostgreSQL session variables the row level policies read.

    A no op on SQLite. Called once per request, after authentication, so the
    backstop policies have something to compare against.
    """
    if db.bind is None or db.bind.dialect.name != "postgresql":
        return
    brand_id = principal.brand_ids[0] if principal.brand_ids else ""
    db.execute(
        _set_config("khazana.role", principal.role.value),
    )
    db.execute(
        _set_config("khazana.brand_id", brand_id),
    )


def _set_config(key: str, value: str) -> Any:
    from sqlalchemy import text

    # Bound parameters, never string interpolation, even for a session
    # variable. set_config with is_local true scopes it to the transaction.
    return text("SELECT set_config(:k, :v, true)").bindparams(k=key, v=value)
