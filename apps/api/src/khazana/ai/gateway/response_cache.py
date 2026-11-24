"""Answer an identical request from a stored reply instead of paying again.

Prompt caching makes the stable prefix of a request cheap. This goes further
for the features where the same input really does deserve the same answer: a
brand that uploads the same spreadsheet twice, rescans the same photographs,
or reprices a lot whose inputs have not changed gets the stored reply, at no
cost and with no wait.

It is off unless a route sets ``response_cache_hours``. The conversational
features keep it off, because a person who asks again expects a fresh reply,
and so do the ones whose input carries the date.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from datetime import timedelta
from typing import Any

from sqlalchemy.orm import Session

from ...models import AiResponseCache
from ...models.base import as_utc, utcnow
from ...models.enums import AiFeature


def cache_key(
    *,
    feature: AiFeature,
    model: str,
    effort: str | None,
    prompt_name: str,
    prompt_version: int,
    system: str,
    user_text: str,
    output_schema: dict[str, Any],
    images: Sequence[bytes],
    brand_id: str | None,
) -> str:
    """Everything that shapes the reply, hashed.

    Unlike the fixture key, the image bytes are hashed: a different photograph
    must never get another photograph's listing.
    """
    payload = json.dumps(
        {
            "feature": feature.value,
            "model": model,
            "effort": effort,
            "prompt": f"{prompt_name}.v{prompt_version}",
            "system": system,
            "user": user_text,
            "schema": output_schema,
            "images": [hashlib.sha256(image).hexdigest() for image in images],
            "brand": brand_id,
        },
        sort_keys=True,
        ensure_ascii=False,
    )
    return hashlib.sha256(payload.encode()).hexdigest()


def lookup(db: Session, key: str) -> AiResponseCache | None:
    """The stored reply for this key, if it has not expired."""
    row = db.get(AiResponseCache, key)
    if row is None or as_utc(row.expires_at) <= utcnow():
        return None
    row.hits += 1
    return row


def store(
    db: Session,
    *,
    key: str,
    feature: AiFeature,
    model: str,
    output: dict[str, Any],
    hours: int,
) -> None:
    """Keep a validated reply for ``hours``, replacing an expired one."""
    expires_at = utcnow() + timedelta(hours=hours)
    row = db.get(AiResponseCache, key)
    if row is None:
        db.add(
            AiResponseCache(
                key=key, feature=feature, model=model, output=output, expires_at=expires_at
            )
        )
    else:
        row.model = model
        row.output = output
        row.expires_at = expires_at
        row.hits = 0
    db.flush()


def purge_expired(db: Session) -> int:
    """Delete expired entries. Run from the daily maintenance job."""
    expired = db.query(AiResponseCache).filter(AiResponseCache.expires_at <= utcnow()).delete()
    db.flush()
    return int(expired)
