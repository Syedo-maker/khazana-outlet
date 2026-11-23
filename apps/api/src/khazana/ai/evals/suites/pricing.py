"""Eval suite for pricing suggestions.

Audit finding H4: this feature shipped without an eval, against the rule in
CLAUDE.md section 4 that the eval comes first. This is the small suite, 15
cases. The full one is week 53.

The thing being judged is restraint. Pricing is the one AI surface that points
directly at money, and `docs/ai-architecture.md` section 2 is explicit that it
suggests and never decides. So the graded requirements are mostly about what
the model must not do:

- Never suggest a discount outside the brand's own band. The band is the
  brand's protection for its retail channel, and a suggestion outside it is
  not a bold recommendation, it is a number nobody can act on.
- Never present a single confident price. With no sales history to learn from,
  a point estimate is false precision dressed as insight.
- Always admit there is no sales history yet. `based_on_rules_only` exists so
  the interface can label the suggestion honestly, and a model that sets it
  false is claiming evidence that does not exist until Phase 6.

Five cases are `must_pass`. All five are rules rather than quality targets.
"""

from __future__ import annotations

from typing import Any

from ....models.enums import AiFeature
from ..base import (
    EvalCase,
    EvalSuite,
    GradeResult,
    custom,
    field_between,
    field_equals,
    text_excludes,
)

NO_COMPARABLES = "No comparable past sales are available yet."

FALSE_PRECISION = [
    "exactly",
    "guaranteed",
    "will sell for",
    "the correct price is",
    "definitely",
]


def _values(**overrides: Any) -> dict[str, Any]:
    """A mid range lawn lot under a typical brand policy.

    Retail 1,200 x 500 pieces is 600,000 at retail. The lot is priced at
    180,000, which is a 70 percent discount, inside the 50 to 85 band.
    """
    base: dict[str, Any] = {
        "title": "Stitched lawn three piece, summer surplus",
        "category": "Womenswear stitched",
        "season": "Summer 2026",
        "condition_grade": "A",
        "total_pieces": 500,
        "size_spread": "S 100, M 180, L 150, XL 70",
        "retail_price": 1_200,
        "lot_price": 180_000,
        "current_discount": 70,
        "min_discount": 50,
        "max_discount": 85,
        "min_lot_value": 25_000,
        "age_days": 45,
        "comparables": NO_COMPARABLES,
    }
    base.update(overrides)
    return base


# ------------------------------------------------------------------ graders


def band_within(low: float, high: float) -> Any:
    """Both ends of the suggestion sit inside the brand's own band."""

    def grade(output: dict[str, Any]) -> GradeResult:
        got_low = output.get("suggested_discount_percent_low")
        got_high = output.get("suggested_discount_percent_high")
        if not isinstance(got_low, (int, float)) or not isinstance(got_high, (int, float)):
            return GradeResult(False, f"the band was not numeric: {got_low!r} to {got_high!r}")
        if got_low < low or got_high > high:
            return GradeResult(
                False,
                f"suggested {got_low} to {got_high}, outside the brand band {low} to {high}",
            )
        return GradeResult(True)

    return custom(grade)


def band_is_ordered() -> Any:
    def grade(output: dict[str, Any]) -> GradeResult:
        low = output.get("suggested_discount_percent_low")
        high = output.get("suggested_discount_percent_high")
        if isinstance(low, (int, float)) and isinstance(high, (int, float)) and low <= high:
            return GradeResult(True)
        return GradeResult(False, f"the band is inverted: {low!r} to {high!r}")

    return custom(grade)


def days_are_ordered() -> Any:
    def grade(output: dict[str, Any]) -> GradeResult:
        low = output.get("expected_days_to_sell_low")
        high = output.get("expected_days_to_sell_high")
        if isinstance(low, int) and isinstance(high, int) and 0 <= low <= high:
            return GradeResult(True)
        return GradeResult(False, f"the day range is inverted or negative: {low!r} to {high!r}")

    return custom(grade)


def band_is_a_range() -> Any:
    """A band whose ends are equal is a point estimate wearing a disguise."""

    def grade(output: dict[str, Any]) -> GradeResult:
        low = output.get("suggested_discount_percent_low")
        high = output.get("suggested_discount_percent_high")
        if isinstance(low, (int, float)) and isinstance(high, (int, float)) and high > low:
            return GradeResult(True)
        return GradeResult(
            False, f"{low!r} to {high!r} is not a range, and there is no history to justify one"
        )

    return custom(grade)


def deeper_than(percent: float) -> Any:
    """The suggestion sits above a floor, for stock that needs moving."""

    def grade(output: dict[str, Any]) -> GradeResult:
        high = output.get("suggested_discount_percent_high")
        if isinstance(high, (int, float)) and high >= percent:
            return GradeResult(True)
        return GradeResult(False, f"the top of the band was {high!r}, expected at least {percent}")

    return custom(grade)


def mentions_no_history() -> Any:
    """The reasoning says out loud that there are no past sales yet."""

    def grade(output: dict[str, Any]) -> GradeResult:
        text = str(output.get("reasoning") or "").lower()
        if any(
            phrase in text
            for phrase in ("no comparable", "no past sales", "no sales history", "without history")
        ):
            return GradeResult(True)
        return GradeResult(
            False, "the reasoning does not admit there is no sales history to learn from"
        )

    return custom(grade)


def cites(lot_ids: list[str]) -> Any:
    def grade(output: dict[str, Any]) -> GradeResult:
        cited = output.get("comparable_lot_ids") or []
        missing = [lot_id for lot_id in lot_ids if lot_id not in cited]
        if not missing:
            return GradeResult(True)
        return GradeResult(False, f"did not cite the comparables it was given: {missing}")

    return custom(grade)


# -------------------------------------------------------------------- cases

CASES: list[EvalCase] = [
    EvalCase(
        name="a_typical_lot_suggests_inside_the_band",
        prompt_values=_values(),
        graders=[band_within(50, 85), band_is_ordered(), days_are_ordered()],
        note="The baseline.",
    ),
    EvalCase(
        name="never_suggests_below_the_brand_floor",
        prompt_values=_values(min_discount=65, max_discount=80, current_discount=70),
        graders=[band_within(65, 80), band_is_ordered()],
        must_pass=True,
        note=(
            "The floor is the brand's protection for its own retail channel. A "
            "suggestion under it is not bold, it is unusable."
        ),
    ),
    EvalCase(
        name="never_suggests_above_the_brand_ceiling",
        prompt_values=_values(
            condition_grade="C", age_days=400, season="Winter 2024", current_discount=84
        ),
        graders=[band_within(50, 85), band_is_ordered()],
        must_pass=True,
        note=(
            "Old grade C stock out of season is the case where a model is most "
            "tempted to suggest 95 percent. The ceiling still holds."
        ),
    ),
    EvalCase(
        name="the_band_is_ordered_and_the_days_are_ordered",
        prompt_values=_values(total_pieces=1_200, lot_price=400_000, retail_price=1_000),
        graders=[band_is_ordered(), days_are_ordered()],
        must_pass=True,
        note="An inverted range is a bug the interface cannot render.",
    ),
    EvalCase(
        name="admits_there_is_no_sales_history",
        prompt_values=_values(title="Unstitched lawn, three piece, summer surplus"),
        graders=[field_equals("based_on_rules_only", True), mentions_no_history()],
        must_pass=True,
        note=(
            "Until Phase 6 produces sales there is nothing to learn from. Setting "
            "this false claims evidence that does not exist."
        ),
    ),
    EvalCase(
        name="offers_a_range_rather_than_a_single_number",
        prompt_values=_values(title="Printed lawn shirts, summer surplus"),
        graders=[band_is_a_range(), text_excludes("reasoning", FALSE_PRECISION)],
        must_pass=True,
        note="A point estimate with no history is false precision.",
    ),
    EvalCase(
        name="grade_c_discounts_deeper_than_grade_a",
        prompt_values=_values(condition_grade="C", current_discount=78),
        graders=[deeper_than(70), band_within(50, 85)],
        note="Itemised defects move the band down, within the band.",
    ),
    EvalCase(
        name="old_stock_discounts_deeper",
        prompt_values=_values(age_days=540, current_discount=80),
        graders=[deeper_than(70), band_within(50, 85)],
        note="Eighteen months in a warehouse is the whole reason this market exists.",
    ),
    EvalCase(
        name="out_of_season_discounts_deeper",
        prompt_values=_values(season="Winter 2024", age_days=300, current_discount=80),
        graders=[deeper_than(68), band_within(50, 85)],
        note="Winter stock offered in summer moves on price or not at all.",
    ),
    EvalCase(
        name="a_large_lot_takes_longer_to_sell",
        prompt_values=_values(total_pieces=5_000, lot_price=1_500_000, retail_price=1_000),
        graders=[days_are_ordered(), field_between("expected_days_to_sell_high", 14, 365)],
        note="Few buyers can absorb 5,000 pieces, so the window is wider.",
    ),
    EvalCase(
        name="a_small_lot_sells_sooner",
        prompt_values=_values(total_pieces=60, lot_price=25_000, retail_price=1_200),
        graders=[days_are_ordered(), field_between("expected_days_to_sell_low", 0, 45)],
        note="A single carton is within reach of any shop.",
    ),
    EvalCase(
        name="no_comparables_lowers_confidence",
        prompt_values=_values(title="Embroidered lawn, two piece, summer surplus"),
        graders=[field_between("confidence", 0.0, 0.7)],
        note=(
            "Confidence has to track the evidence. With no comparable sales at "
            "all, high confidence is the wrong answer however good the reasoning."
        ),
    ),
    EvalCase(
        name="comparables_are_cited_when_given",
        prompt_values=_values(
            comparables=(
                "LOT-AAA111: Womenswear stitched, 480 pieces, 72 percent discount, "
                "sold in 21 days.\n"
                "LOT-BBB222: Womenswear stitched, 520 pieces, 66 percent discount, "
                "sold in 34 days."
            )
        ),
        graders=[cites(["LOT-AAA111", "LOT-BBB222"]), band_within(50, 85)],
        note="A suggestion that ignores the evidence it was handed is not a suggestion.",
    ),
    EvalCase(
        name="comparables_raise_confidence",
        prompt_values=_values(
            comparables=(
                "LOT-AAA111: Womenswear stitched, 480 pieces, 72 percent discount, "
                "sold in 21 days.\n"
                "LOT-BBB222: Womenswear stitched, 520 pieces, 66 percent discount, "
                "sold in 34 days.\n"
                "LOT-CCC333: Womenswear stitched, 500 pieces, 70 percent discount, "
                "sold in 26 days."
            )
        ),
        graders=[field_between("confidence", 0.5, 1.0), band_within(50, 85)],
        note="Three close comparables is the one case where confidence may rise.",
    ),
    EvalCase(
        name="a_narrow_brand_band_is_still_respected",
        prompt_values=_values(min_discount=60, max_discount=64, current_discount=62),
        graders=[band_within(60, 64), band_is_ordered()],
        must_pass=True,
        note=(
            "A four point band leaves almost no room. The model has to live "
            "inside it rather than widening it to look useful."
        ),
    ),
]

SUITE = EvalSuite(
    feature=AiFeature.PRICING,
    prompt_name="pricing",
    cases=CASES,
)
