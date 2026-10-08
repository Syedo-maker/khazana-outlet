"""Structured output schemas for the AI features.

Every feature returns validated structured data, not prose that something
later has to parse. These models are passed to the API as the output schema
and used to validate what comes back, so a malformed response is an error at
the gateway rather than a strange bug three layers up.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from ..models.enums import ConditionGrade


class ListingDraft(BaseModel):
    """What the photo to listing feature produces.

    This is a draft. A human always reviews it, and both the draft and the
    correction are stored, which is the quality metric and the future training
    corpus in one.
    """

    model_config = ConfigDict(extra="forbid")

    title: str = Field(max_length=200, description="Short, factual, no marketing language")
    description: str = Field(max_length=2000)
    # Must be one of the slugs from the categories table, which is supplied in
    # the prompt. The model does not invent a taxonomy.
    category_slug: str = Field(max_length=120)
    colors: list[str] = Field(default_factory=list, max_length=12)
    material: str | None = Field(default=None, max_length=120)
    apparent_condition: ConditionGrade
    suggested_sizes: list[str] = Field(default_factory=list, max_length=24)
    tags: list[str] = Field(default_factory=list, max_length=20)
    # Low confidence is a routing signal, not a decoration: anything under the
    # review threshold goes to a human before it can be submitted.
    confidence: float = Field(ge=0, le=1)
    # What the model could not tell from the photographs. Shown to the brand
    # as the list of fields to check, which is far more useful than a silent
    # guess.
    uncertain_fields: list[str] = Field(default_factory=list)


class ManifestLineDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")

    size: str = Field(max_length=32)
    color: str = Field(max_length=48)
    pieces: int = Field(gt=0)


class ManifestDraft(BaseModel):
    """Extraction from a brand spreadsheet.

    ``declared_total`` is what the file said and ``line_total`` is what the
    rows add up to. When they differ, the gateway does not reconcile silently:
    it reports the difference and every change it would make, for a human to
    accept or reject.
    """

    model_config = ConfigDict(extra="forbid")

    lines: list[ManifestLineDraft]
    declared_total: int | None = None
    notes: list[str] = Field(default_factory=list)
    # Human readable description of each change the extractor wants to make.
    proposed_corrections: list[str] = Field(default_factory=list)
    confidence: float = Field(ge=0, le=1)

    @property
    def line_total(self) -> int:
        return sum(line.pieces for line in self.lines)

    @property
    def is_balanced(self) -> bool:
        return self.declared_total is None or self.line_total == self.declared_total


class PriceSuggestion(BaseModel):
    """A band and a reason, never a single confident number.

    With no sales history this is informed guesswork, and presenting it as a
    band with its reasoning is the honest way to show that. It becomes a real
    prediction in Phase 6 when actual sales exist to learn from.
    """

    model_config = ConfigDict(extra="forbid")

    suggested_discount_percent_low: float = Field(ge=0, le=95)
    suggested_discount_percent_high: float = Field(ge=0, le=95)
    expected_days_to_sell_low: int = Field(ge=0)
    expected_days_to_sell_high: int = Field(ge=0)
    reasoning: str = Field(max_length=1200)
    comparable_lot_ids: list[str] = Field(default_factory=list)
    confidence: float = Field(ge=0, le=1)
    # True while the model has no real sales to learn from, so the interface
    # can label the suggestion honestly.
    based_on_rules_only: bool = True


class RiskFinding(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: str = Field(max_length=60)
    detail: str = Field(max_length=500)
    severity: int = Field(ge=1, le=5)


class RiskScore(BaseModel):
    """Orders the admin queue. Never blocks anything on its own."""

    model_config = ConfigDict(extra="forbid")

    score: int = Field(ge=0, le=100, description="Higher means more concerning")
    findings: list[RiskFinding] = Field(default_factory=list)
    completeness: int = Field(ge=0, le=100)
    manifest_consistent: bool
    price_plausible: bool
    counterfeit_signals: list[str] = Field(default_factory=list)
    recommend_human_review: bool


class AssistantAnswer(BaseModel):
    """A grounded answer.

    ``tool_calls_made`` exists so the eval can assert the rule that matters:
    a factual claim about stock, price or an order must come from a tool call
    against the database. An answer with no tool calls that nonetheless states
    a price is a failure, however plausible it reads.
    """

    model_config = ConfigDict(extra="forbid")

    answer: str
    language: str = Field(description="en, ur or ur_roman")
    tool_calls_made: list[str] = Field(default_factory=list)
    lot_ids_referenced: list[str] = Field(default_factory=list)
    # Set when the assistant declined to answer because the data was not
    # available. Saying so is the correct behaviour, not a failure.
    declined: bool = False
    decline_reason: str | None = None


SCHEMA_BY_FEATURE: dict[str, type[BaseModel]] = {
    "listing_from_photos": ListingDraft,
    "manifest_extract": ManifestDraft,
    "pricing": PriceSuggestion,
    "risk_scoring": RiskScore,
    "assistant_buyer": AssistantAnswer,
    "assistant_brand": AssistantAnswer,
}
