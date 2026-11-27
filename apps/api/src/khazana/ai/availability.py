"""Whether the AI features can run right now, without making a call.

Two things stop them: AI switched off for the deployment (AI_ENABLED=false,
for running with no Anthropic key) and today's spend reaching the daily cap.
Either way every feature falls back to its manual path; see
docs/ai-architecture.md, "When AI is not available".
"""

from __future__ import annotations

from decimal import Decimal

from sqlalchemy.orm import Session

from ..config import get_settings


def available_today(db: Session) -> bool:
    settings = get_settings()
    if not settings.ai_enabled:
        return False
    from .gateway import limits

    cap = Decimal(str(settings.ai_daily_spend_limit_usd))
    return cap <= 0 or limits.spend_today(db) < cap
