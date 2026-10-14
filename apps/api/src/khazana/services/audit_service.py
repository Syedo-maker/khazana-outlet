"""The audit trail.

The `audit_log` table has existed since Phase 1 but nothing wrote to it, which
was correct: Phase 1 and 2 had no consequential actions to record. Phase 3 is
where verification decisions, approvals, order state changes and payouts
start happening, so this is where writing begins.

Three rules that make an audit trail worth having:

1. **Record what changed, not that something changed.** A row saying "brand
   updated" answers nothing six months later. The before and after snapshots
   are the point.
2. **Record who, including when it was not a person.** A change made by a
   scheduled job or triggered by a model must be distinguishable from one a
   human made, or the log quietly implies a person approved something they
   never saw.
3. **Never fail the action because the log failed.** An audit write that
   breaks a payout is worse than a missing audit row. Failures here are
   logged loudly and swallowed.

The table is append only, enforced by a trigger in migration 0001, so there is
no update or delete path here by design.
"""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy.orm import Session

from ..models import AuditLog
from ..models.enums import UserRole

logger = logging.getLogger(__name__)

# What acted. "user" is a person, "system" is a scheduled or automatic path,
# and "ai" is anything a model initiated, which must never be mistaken for a
# human decision.
ACTOR_USER = "user"
ACTOR_SYSTEM = "system"
ACTOR_AI = "ai"

# Values a snapshot must never carry into the log.
REDACTED_FIELDS = frozenset(
    {
        "password",
        "password_hash",
        "code_hash",
        "token",
        "token_hash",
        "access_token",
        "refresh_token",
        "secret",
        "api_key",
        "anthropic_api_key",
    }
)
REDACTED = "[redacted]"


def record(
    db: Session,
    *,
    action: str,
    entity_type: str,
    entity_id: str | None = None,
    brand_id: str | None = None,
    actor_user_id: str | None = None,
    actor_role: UserRole | str | None = None,
    actor_kind: str = ACTOR_USER,
    before: dict[str, Any] | None = None,
    after: dict[str, Any] | None = None,
    note: str | None = None,
    ip: str | None = None,
    user_agent: str | None = None,
) -> AuditLog | None:
    """Append one entry. Returns None if the write failed.

    Deliberately does not commit. The entry belongs to the same transaction as
    the change it describes, so that a rolled back action cannot leave an audit
    row claiming it happened.
    """
    try:
        entry = AuditLog(
            actor_user_id=actor_user_id,
            actor_role=_role_value(actor_role),
            actor_kind=actor_kind,
            action=action,
            entity_type=entity_type,
            entity_id=entity_id,
            brand_id=brand_id,
            before=redact(before),
            after=redact(after),
            note=note[:2000] if note else None,
            ip=ip,
            user_agent=user_agent[:255] if user_agent else None,
        )
        db.add(entry)
        db.flush()
        return entry
    except Exception:
        # An audit write must never take down the action it describes. A
        # payout that fails because logging failed is the worse outcome.
        logger.exception(
            "audit write failed, action=%s entity=%s/%s", action, entity_type, entity_id
        )
        return None


def snapshot(instance: object, fields: tuple[str, ...]) -> dict[str, Any]:
    """Capture named fields from a model instance, JSON safe.

    Explicit field list rather than everything on the object. A blanket dump
    grows silently when a column is added, and that is how a secret ends up in
    an append only table that cannot be edited afterwards.
    """
    captured: dict[str, Any] = {}
    for name in fields:
        value = getattr(instance, name, None)
        captured[name] = _jsonable(value)

    # redact accepts None for callers that may not have a payload. Here there
    # is always a dict, so the None branch cannot be reached.
    redacted = redact(captured)
    assert redacted is not None
    return redacted


def redact(payload: dict[str, Any] | None) -> dict[str, Any] | None:
    """Replace anything that looks like a credential."""
    if payload is None:
        return None
    return {
        key: (REDACTED if key.lower() in REDACTED_FIELDS else _jsonable(value))
        for key, value in payload.items()
    }


def diff(before: dict[str, Any], after: dict[str, Any]) -> dict[str, Any]:
    """Only the fields that actually changed.

    Storing the whole object twice makes a reader hunt for the change. Storing
    just the delta makes the log readable, which is the difference between an
    audit trail people use and one they ignore.
    """
    changed: dict[str, Any] = {}
    for key in set(before) | set(after):
        old, new = before.get(key), after.get(key)
        if old != new:
            changed[key] = {"from": old, "to": new}
    return changed


def _role_value(role: UserRole | str | None) -> str | None:
    if role is None:
        return None
    return role.value if isinstance(role, UserRole) else str(role)


def _jsonable(value: Any) -> Any:
    """Make a value safe to store as JSON.

    Decimals, dates, enums and UUIDs all appear in these snapshots and none of
    them serialise on their own.
    """
    from datetime import date, datetime
    from decimal import Decimal
    from enum import Enum

    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    return str(value)
