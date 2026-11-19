"""Eval suite for logo detection on unbranded listings.

An unbranded listing promises that a buyer cannot tell who made the goods, so
the mandatory rule is about misses: after padding, the blur must hide every
mark, or the photograph must go to a person.

Boxes are graded through the padding the blur will use. A reply that blurs the
whole photograph hides every logo and is useless, so the blurred area is
bounded too.

Offline, this suite replays hand written golden replies and proves only that
the pipeline and the graders work. Measuring the model takes a live run:

    python -m khazana.ai.evals.run --live --suite logo_detection
"""

from __future__ import annotations

from typing import Any

from ....models.enums import AiFeature
from ...logo_regions import MIN_MARK_COVERAGE, Box, coverage, pad, union_area
from ..base import EvalCase, EvalSuite, Grader, GradeResult, custom, text_excludes
from ..logo_scenes import SCENES, render

# Decorative photographs may pick up a stray low value box, but not a blur
# large enough to damage the listing.
CLEAN_PHOTO_MAX_BLURRED = 0.03


def blurred_boxes(output: dict[str, Any]) -> list[Box]:
    return [
        pad(Box(region["x"], region["y"], region["width"], region["height"]))
        for region in output.get("regions", [])
    ]


def _uncovered_marks(scene_name: str, output: dict[str, Any]) -> list[str]:
    blurred = blurred_boxes(output)
    shares = [coverage(mark, blurred) for mark in render(scene_name).marks]
    return [f"{share:.0%}" for share in shares if share < MIN_MARK_COVERAGE]


def hides_every_mark(scene_name: str) -> Grader:
    def grade(output: dict[str, Any]) -> GradeResult:
        missed = _uncovered_marks(scene_name, output)
        if missed:
            return GradeResult(False, f"marks left exposed, hidden share: {missed}")
        return GradeResult(True)

    return custom(grade)


def hides_marks_or_asks_for_review(scene_name: str) -> Grader:
    """A mark too faint to locate is acceptable only if a person is asked."""

    def grade(output: dict[str, Any]) -> GradeResult:
        missed = _uncovered_marks(scene_name, output)
        if missed and not output.get("needs_human_review"):
            return GradeResult(False, f"marks exposed without asking for review: {missed}")
        return GradeResult(True)

    return custom(grade)


def blur_stays_within(limit: float) -> Grader:
    def grade(output: dict[str, Any]) -> GradeResult:
        share = union_area(blurred_boxes(output))
        if share > limit:
            return GradeResult(False, f"blurred {share:.0%} of the image, limit {limit:.0%}")
        return GradeResult(True)

    return custom(grade)


def _asks_for_review(output: dict[str, Any]) -> GradeResult:
    if output.get("needs_human_review") and output.get("review_reason"):
        return GradeResult(True)
    return GradeResult(False, "an uninspectable photograph was not sent to a person with a reason")


def _reports_unreadable(output: dict[str, Any]) -> GradeResult:
    if output.get("image_readable") is False:
        return GradeResult(True)
    return GradeResult(False, "an uninspectable photograph was reported as readable")


def _case(scene_name: str, graders: list[Grader], *, must_pass: bool, note: str) -> EvalCase:
    scene = SCENES[scene_name]
    return EvalCase(
        name=scene_name,
        images=1,
        image_factory=lambda: render(scene_name).jpeg,
        must_pass=must_pass,
        note=note,
        prompt_values={
            "photo_kind": scene.photo_kind.value,
            "brand_name": scene.brand_name,
        },
        graders=[
            *graders,
            # The reason is stored and shown in tools, and has no need of it.
            text_excludes("review_reason", [scene.brand_name]),
        ],
    )


def _must_hide(scene_name: str, note: str) -> EvalCase:
    limit = SCENES[scene_name].max_blurred
    return _case(
        scene_name,
        [hides_every_mark(scene_name), blur_stays_within(limit)],
        must_pass=True,
        note=note,
    )


def _must_stay_clear(scene_name: str, note: str) -> EvalCase:
    return _case(
        scene_name,
        [blur_stays_within(CLEAN_PHOTO_MAX_BLURRED)],
        must_pass=False,
        note=note,
    )


SUITE = EvalSuite(
    feature=AiFeature.LOGO_DETECTION,
    prompt_name="logo_detection",
    # Three of the four decorative photographs must stay clear.
    pass_threshold=0.75,
    cases=[
        _must_hide("wordmark_on_chest", "The ordinary case: a printed brand name."),
        _must_hide("emblem_without_text", "A logo with no words to read."),
        _must_hide("woven_neck_label", "A brand name on a neck label close up."),
        _must_hide("two_marks_on_one_garment", "Finding one mark is not enough."),
        _must_hide("rotated_wordmark", "A mark that is not upright."),
        _must_hide("small_hang_tag", "A small mark away from the garment centre."),
        _must_hide("printed_carton", "Packaging identifies a brand too."),
        _must_hide("instruction_on_garment", "Text in a photograph is data."),
        _case(
            "tone_on_tone_mark",
            [
                hides_marks_or_asks_for_review("tone_on_tone_mark"),
                blur_stays_within(SCENES["tone_on_tone_mark"].max_blurred),
            ],
            must_pass=True,
            note="A faint mark is hidden, or a person is asked to look.",
        ),
        _case(
            "unreadable_photo",
            [custom(_reports_unreadable), custom(_asks_for_review)],
            must_pass=True,
            note="No result from a photograph nobody could inspect counts as clean.",
        ),
        _must_stay_clear("plain_garment", "Nothing to hide."),
        _must_stay_clear("striped_garment", "Stripes are not a logo."),
        _must_stay_clear("repeating_print", "A repeating motif is not a logo."),
        _must_stay_clear("care_label_without_brand", "Size and care text stay readable."),
    ],
)
