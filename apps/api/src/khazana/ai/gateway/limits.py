"""Spend caps and per feature kill switches.

Both are checked before a call is made. A cap checked afterwards is not a cap,
it is a report.
"""

from __future__ import annotations

import os
from datetime import timedelta
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ...config import get_settings
from ...core.errors import FeatureDisabled, SpendLimitReached
from ...models import AiSpend, BrandPolicy
from ...models.base import utcnow
from ...models.enums import AiFeature


def feature_switches() -> dict[str, bool]:
    """Which AI features are currently enabled.

    Read from the environment so a feature can be switched off in production
    without a deployment. The name of the variable for a feature is
    ``AI_DISABLE_<FEATURE>``, for example ``AI_DISABLE_PRICING=true``.
    """
    return {feature.value: not _is_disabled(feature) for feature in AiFeature}


def _is_disabled(feature: AiFeature) -> bool:
    flag = os.environ.get(f"AI_DISABLE_{feature.value.upper()}", "").strip().lower()
    return flag in {"1", "true", "yes", "on"}


def assert_feature_enabled(feature: AiFeature) -> None:
    if _is_disabled(feature):
        raise FeatureDisabled(
            f"The {feature.value.replace('_', ' ')} feature is temporarily switched off."
        )


def spend_today(db: Session, feature: AiFeature | None = None) -> Decimal:
    statement = select(func.coalesce(func.sum(AiSpend.cost_usd), 0)).where(
        AiSpend.day == utcnow().date()
    )
    if feature is not None:
        statement = statement.where(AiSpend.feature == feature)
    return Decimal(str(db.scalar(statement) or 0))


def spend_this_month(db: Session, brand_id: str) -> Decimal:
    since = (utcnow() - timedelta(days=30)).date()
    return Decimal(
        str(
            db.scalar(
                select(func.coalesce(func.sum(AiSpend.cost_usd), 0)).where(
                    AiSpend.brand_id == brand_id, AiSpend.day >= since
                )
            )
            or 0
        )
    )


def assert_within_budget(
    db: Session,
    feature: AiFeature,
    brand_id: str | None = None,
    projected_cost_usd: Decimal | None = None,
) -> None:
    """Raise before spending money that would breach a cap.

    Two caps, checked in order of blast radius. The platform daily cap protects
    you from a runaway loop. The per brand monthly cap stops one brand's bulk
    upload consuming the budget for everyone else, and it reads the brand's own
    policy row rather than a global constant.
    """
    assert_feature_enabled(feature)

    settings = get_settings()
    projected = projected_cost_usd or Decimal("0")

    # At the cap means stop, not one more call. Using greater than would let
    # every budget overshoot by one request, which on a bulk upload is
    # hundreds of requests.
    daily_limit = Decimal(str(settings.ai_daily_spend_limit_usd))
    if daily_limit > 0 and spend_today(db) + projected >= daily_limit:
        raise SpendLimitReached(
            "The daily AI budget has been reached. Work has been queued and will "
            "resume tomorrow, or raise AI_DAILY_SPEND_LIMIT_USD."
        )

    if brand_id is None:
        return

    policy = db.scalars(select(BrandPolicy).where(BrandPolicy.brand_id == brand_id)).first()
    brand_limit = (
        Decimal(str(policy.ai_monthly_budget_usd))
        if policy is not None
        else Decimal(str(settings.ai_brand_monthly_spend_limit_usd))
    )
    if brand_limit > 0 and spend_this_month(db, brand_id) + projected >= brand_limit:
        raise SpendLimitReached(
            "This brand has reached its monthly AI allowance. Raise it in the "
            "brand policy, or wait for the next period."
        )
