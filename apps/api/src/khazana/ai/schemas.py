"""Structured output schemas for the AI features.

Every feature returns validated structured data, not prose that something
later has to parse. These models are passed to the API as the output schema
and used to validate what comes back, so a malformed response is an error at
the gateway rather than a strange bug three layers up.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

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


class LogoRegion(BaseModel):
    """One possible brand mark, as fractions of the image."""

    model_config = ConfigDict(extra="forbid")

    kind: Literal["logo", "brand_text", "label", "packaging", "other"]
    x: float = Field(ge=0, le=1)
    y: float = Field(ge=0, le=1)
    width: float = Field(ge=0, le=1)
    height: float = Field(ge=0, le=1)
    confidence: float = Field(ge=0, le=1)


class LogoDetection(BaseModel):
    """Where the brand marks are in one photograph.

    Every field is required, so a reply cannot pass by leaving out the signal
    that a person needs to look.
    """

    model_config = ConfigDict(extra="forbid")

    regions: list[LogoRegion] = Field(max_length=24)
    image_readable: bool
    needs_human_review: bool
    review_reason: str | None = Field(max_length=300)


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


TOOL_ARGUMENT_FIELDS = (
    "query",
    "category",
    "city",
    "max_price_per_piece_pkr",
    "lot_code",
    "pieces",
    "order_code",
    "to_city",
)


class PlannedToolCall(BaseModel):
    """One planned lookup, with each possible argument as its own field.

    A free form arguments object cannot be expressed in the closed schema the
    structured output API requires, so every argument any tool takes is listed
    here and the ones a tool does not use stay null. Which ones apply is checked
    against the tool itself when the plan runs, so a malformed plan becomes a
    recoverable error rather than a lost turn.
    """

    model_config = ConfigDict(extra="forbid")

    tool: str = Field(max_length=60)
    query: str | None = Field(default=None, max_length=200)
    category: str | None = Field(default=None, max_length=120)
    city: str | None = Field(default=None, max_length=80)
    max_price_per_piece_pkr: int | None = None
    lot_code: str | None = Field(default=None, max_length=24)
    pieces: int | None = None
    order_code: str | None = Field(default=None, max_length=24)
    to_city: str | None = Field(default=None, max_length=80)

    @model_validator(mode="before")
    @classmethod
    def _unpack_arguments(cls, value: Any) -> Any:
        """Accept the older shape, an ``arguments`` object, and flatten it.

        Keys that are not arguments of any tool are dropped here, and the call
        then fails at the tool for the argument it is missing.
        """
        if isinstance(value, dict) and isinstance(value.get("arguments"), dict):
            flattened = {key: item for key, item in value.items() if key != "arguments"}
            for key, item in value["arguments"].items():
                if key in TOOL_ARGUMENT_FIELDS:
                    flattened.setdefault(key, item)
            return flattened
        return value

    @property
    def arguments(self) -> dict[str, Any]:
        """The arguments that were filled in."""
        return {
            name: getattr(self, name)
            for name in TOOL_ARGUMENT_FIELDS
            if getattr(self, name) is not None
        }


class ToolPlan(BaseModel):
    """Which tools to run for one buyer message.

    The assistant is deliberately split into a plan step and an answer step
    rather than a native tool use loop. Both steps are single structured
    calls, which means the existing gateway handles them unchanged, each step
    is independently evaluable, and the cost of a turn is bounded at two calls
    instead of however many the model decides to make.

    The trade is that the model cannot react to a tool result by calling
    another tool in the same turn. For a buyer asking about stock that is
    rarely needed, and a follow up question gets a fresh turn. Native tool use
    is the Phase 4 upgrade, once there is usage data showing where one round
    is not enough.
    """

    model_config = ConfigDict(extra="forbid")

    calls: list[PlannedToolCall] = Field(default_factory=list, max_length=6)
    # Set when the message needs no lookup at all, for example a greeting.
    needs_no_tools: bool = False
    language: str = Field(description="en, ur or ur_roman")


BRAND_TOOL_ARGUMENT_FIELDS = ("lot_code", "city", "category", "days", "min_days_live")


class BrandToolCall(BaseModel):
    """One planned lookup for the brand assistant.

    There is no brand identifier among the fields, deliberately. Which brand's
    data a lookup reads comes from the signed in session, so a plan cannot ask
    for another brand's numbers however the message is worded.
    """

    model_config = ConfigDict(extra="forbid")

    tool: str = Field(max_length=60)
    lot_code: str | None = Field(default=None, max_length=24)
    city: str | None = Field(default=None, max_length=80)
    category: str | None = Field(default=None, max_length=120)
    days: int | None = Field(default=None, description="Look back period in days")
    min_days_live: int | None = Field(
        default=None, description="Slow means live at least this long"
    )

    @property
    def arguments(self) -> dict[str, Any]:
        return {
            name: getattr(self, name)
            for name in BRAND_TOOL_ARGUMENT_FIELDS
            if getattr(self, name) is not None
        }


class BrandToolPlan(BaseModel):
    """Which lookups to run for one question from a brand."""

    model_config = ConfigDict(extra="forbid")

    calls: list[BrandToolCall] = Field(default_factory=list, max_length=5)
    needs_no_tools: bool = False
    language: str = Field(description="en, ur or ur_roman")


class ResellKitCopy(BaseModel):
    """The words in a resell kit. Prices, sizes and photos are added by code.

    The model never sees the brand's retail price or, for an unbranded lot,
    the brand. What it was not given it cannot repeat, which is a stronger
    guarantee than an instruction not to.
    """

    model_config = ConfigDict(extra="forbid")

    caption_en: str = Field(description="Two or three sentences, English")
    caption_ur_roman: str = Field(description="The same, Roman Urdu in Latin letters")
    caption_ur: str = Field(description="The same, Urdu script")
    social_post: str = Field(description="A Facebook or Instagram post, English and Roman Urdu")
    whatsapp_status: str = Field(description="One short line for a WhatsApp status")
    hashtags: list[str] = Field(default_factory=list, max_length=10)
    selling_points: list[str] = Field(
        default_factory=list, max_length=5, description="Each taken from the facts given"
    )


class BargainReply(BaseModel):
    """One counter offer. The price is clamped by code before anyone sees it."""

    model_config = ConfigDict(extra="forbid")

    counter_price_per_piece_pkr: int = Field(description="Within the range you were given")
    message: str = Field(description="The reply to the buyer, in their language")
    language: str = Field(description="en, ur or ur_roman")


class MarkdownDecision(BaseModel):
    """How far to lower one lot this time. Clamped by code to the brand's step."""

    model_config = ConfigDict(extra="forbid")

    reduce_by_percent: float = Field(description="Between 0 and the step you were given")
    reason: str = Field(description="One sentence, from the facts given")


SCHEMA_BY_FEATURE: dict[str, type[BaseModel]] = {
    "listing_from_photos": ListingDraft,
    "logo_detection": LogoDetection,
    "manifest_extract": ManifestDraft,
    "pricing": PriceSuggestion,
    "risk_scoring": RiskScore,
    "assistant_buyer": AssistantAnswer,
    "assistant_brand": AssistantAnswer,
    "resell_kit": ResellKitCopy,
    "bargaining": BargainReply,
    "markdown": MarkdownDecision,
}
