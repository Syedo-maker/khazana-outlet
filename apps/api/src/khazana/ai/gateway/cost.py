"""Cost calculation and the spend ledger.

Every call is priced from the token counts the API returns, never estimated,
and written to ``ai_spend`` the same transaction it is recorded in. That is
what makes the cap in ``limits.py`` enforceable rather than advisory.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from ...models import AiSpend
from ...models.base import utcnow
from ...models.enums import AiFeature, AiMode
from .models import BATCH_DISCOUNT, spec_for

MILLION = Decimal(1_000_000)


@dataclass(frozen=True, slots=True)
class Usage:
    """Token counts as reported by the API."""

    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0

    @property
    def total_tokens(self) -> int:
        return (
            self.input_tokens
            + self.output_tokens
            + self.cache_read_tokens
            + self.cache_write_tokens
        )


def price_call(model_id: str, usage: Usage, mode: AiMode = AiMode.LIVE) -> Decimal:
    """Return the cost of one call in US dollars.

    Decimal rather than float throughout. Fractions of a cent accumulated over
    a hundred thousand calls are the difference between a budget that works
    and one that quietly drifts.
    """
    spec = spec_for(model_id)

    plain_input = Decimal(usage.input_tokens) * Decimal(str(spec.input_per_mtok)) / MILLION
    output = Decimal(usage.output_tokens) * Decimal(str(spec.output_per_mtok)) / MILLION

    # An unverified cache read price is charged at the full input rate. Over
    # reporting a cost is recoverable; under reporting it is a surprise bill.
    read_rate = (
        Decimal(str(spec.cache_read_per_mtok))
        if spec.cache_read_per_mtok is not None
        else Decimal(str(spec.input_per_mtok))
    )
    cache_read = Decimal(usage.cache_read_tokens) * read_rate / MILLION

    write_rate = Decimal(str(spec.input_per_mtok)) * Decimal(str(spec.cache_write_multiplier))
    cache_write = Decimal(usage.cache_write_tokens) * write_rate / MILLION

    total = plain_input + output + cache_read + cache_write

    if mode == AiMode.BATCH:
        total *= Decimal(str(BATCH_DISCOUNT))

    # Offline fixture runs cost nothing, and saying so explicitly stops a
    # development session polluting the spend history.
    if mode == AiMode.OFFLINE:
        return Decimal("0")

    return total.quantize(Decimal("0.000001"))


def record_spend(
    db: Session,
    *,
    feature: AiFeature,
    brand_id: str | None,
    cost_usd: Decimal,
    calls: int = 1,
) -> None:
    """Add to today's ledger row for this feature and brand.

    Upsert by hand rather than with a database specific ON CONFLICT, because
    this has to work identically on PostgreSQL and on SQLite in tests.
    """
    if cost_usd <= 0 and calls == 0:
        return

    today = utcnow().date()
    row = db.scalars(
        select(AiSpend).where(
            AiSpend.day == today,
            AiSpend.feature == feature,
            AiSpend.brand_id.is_(brand_id) if brand_id is None else AiSpend.brand_id == brand_id,
        )
    ).first()

    if row is None:
        db.add(
            AiSpend(
                day=today,
                feature=feature,
                brand_id=brand_id,
                calls=calls,
                cost_usd=cost_usd,
            )
        )
        # Flush so that a second call in the same transaction finds this row
        # instead of inserting a duplicate. The session runs with autoflush
        # off, so the select above would not see a pending insert.
        db.flush()
    else:
        row.calls += calls
        row.cost_usd = row.cost_usd + cost_usd


def estimate_listing_cost(
    model_id: str,
    *,
    images: int,
    tokens_per_image: int = 1_500,
    cached_prefix_tokens: int = 2_000,
    variable_input_tokens: int = 500,
    output_tokens: int = 600,
) -> Decimal:
    """Rough forward estimate, used by the cost dashboard and by planning.

    ``tokens_per_image`` is a placeholder. Measure the real figure with the
    token counting endpoint in Phase 2 and pass it in, because image tokens
    dominate this call and a wrong assumption here is a wrong budget.
    """
    usage = Usage(
        input_tokens=images * tokens_per_image + variable_input_tokens,
        output_tokens=output_tokens,
        cache_read_tokens=cached_prefix_tokens,
    )
    return price_call(model_id, usage)
