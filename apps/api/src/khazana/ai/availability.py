"""Whether the AI features can run right now, without making a call.

Two things stop them: AI switched off for the deployment (AI_ENABLED=false,
for running with no Anthropic key) and today's spend reaching the daily cap.
Either way every feature falls back to its manual path; see
docs/ai-architecture.md, "When AI is not available".
"""

from __future__ import annotations

from decimal import Decimal

from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..config import get_settings
from .gateway.service import AiResult


def available_today(db: Session) -> bool:
    settings = get_settings()
    if not settings.ai_enabled:
        return False
    from .gateway import limits

    cap = Decimal(str(settings.ai_daily_spend_limit_usd))
    return cap <= 0 or limits.spend_today(db) < cap


MANUAL_MODEL = "manual"


def reason(exc: Exception) -> str:
    """Why the manual path is showing, in words for the person using it."""
    from ..core.errors import AiSwitchedOff, SpendLimitReached

    if isinstance(exc, AiSwitchedOff):
        return "The AI helper is switched off on this server, so this is done by hand."
    if isinstance(exc, SpendLimitReached):
        return (
            "Today's AI budget is used up, so this is done by hand. The AI helper is back tomorrow."
        )
    return "The AI helper is not available right now, so this is done by hand."


def manual_result(output: BaseModel) -> AiResult:
    """What a feature returns when no model was called: nothing was spent."""
    return AiResult(
        output=output,
        job_id="",
        output_id="",
        model=MANUAL_MODEL,
        cost_usd=Decimal(0),
        latency_ms=0,
        from_fixture=False,
    )
