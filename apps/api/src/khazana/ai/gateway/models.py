"""The model catalogue and its prices.

One table, one source of truth. When Anthropic changes a price or ships a
model, this file is the only edit, and ``cost.py`` reads from it.

Prices are US dollars per million tokens, taken from the current Anthropic
pricing for the first party API. Figures marked UNVERIFIED are not published
in the source used to build this table, so the code is deliberately
conservative about them rather than guessing cheap and under reporting spend.
"""

from __future__ import annotations

from dataclasses import dataclass

# Model identifiers. Never build these by appending a date suffix.
OPUS_5_5 = "claude-opus-5-5"
SONNET_5_5 = "claude-sonnet-5-5"
HAIKU_4_5 = "claude-haiku-4-5"


@dataclass(frozen=True, slots=True)
class ModelSpec:
    model_id: str
    input_per_mtok: float
    output_per_mtok: float
    # Cost of reading a cached prefix. None means the published figure was not
    # confirmed, and cost.py then charges the full input rate, so an unknown
    # never makes the bill look smaller than it is.
    cache_read_per_mtok: float | None
    # Writing a cache entry costs more than a plain input token. The usual
    # multiple is 1.25, which is what this defaults to, but it is marked
    # UNVERIFIED and should be confirmed against a real invoice in Phase 2.
    cache_write_multiplier: float
    context_window: int
    supports_vision: bool
    # Opus 5.5 and Sonnet 5.5 always think. Sending thinking disabled or a
    # token budget to them returns a 400, so effort is the only lever.
    thinking_always_on: bool
    # Haiku 4.5 still takes the older budget_tokens form, so it is not a drop
    # in replacement for an Opus route.
    uses_budget_tokens: bool


CATALOGUE: dict[str, ModelSpec] = {
    OPUS_5_5: ModelSpec(
        model_id=OPUS_5_5,
        input_per_mtok=4.00,
        output_per_mtok=20.00,
        cache_read_per_mtok=0.20,
        cache_write_multiplier=1.25,  # UNVERIFIED
        context_window=1_000_000,
        supports_vision=True,
        thinking_always_on=True,
        uses_budget_tokens=False,
    ),
    SONNET_5_5: ModelSpec(
        model_id=SONNET_5_5,
        input_per_mtok=2.00,
        output_per_mtok=10.00,
        cache_read_per_mtok=0.20,
        cache_write_multiplier=1.25,  # UNVERIFIED
        context_window=1_000_000,
        supports_vision=True,
        thinking_always_on=True,
        uses_budget_tokens=False,
    ),
    HAIKU_4_5: ModelSpec(
        model_id=HAIKU_4_5,
        input_per_mtok=1.00,
        output_per_mtok=5.00,
        cache_read_per_mtok=None,  # UNVERIFIED, charged at the input rate
        cache_write_multiplier=1.25,  # UNVERIFIED
        context_window=200_000,
        supports_vision=True,
        thinking_always_on=False,
        uses_budget_tokens=True,
    ),
}

# Batch processing runs at half price. Applied in cost.py, not here, because
# it is a property of how a call was made rather than of the model.
BATCH_DISCOUNT = 0.50


def spec_for(model_id: str) -> ModelSpec:
    try:
        return CATALOGUE[model_id]
    except KeyError as exc:
        raise ValueError(
            f"Unknown model {model_id!r}. Add it to CATALOGUE with its prices "
            "before routing traffic to it, so spend stays measurable."
        ) from exc
