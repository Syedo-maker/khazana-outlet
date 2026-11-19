"""The logo detection eval has to be able to fail.

Its offline fixtures are written from the known answers, so a green offline
run says little by itself. These tests feed the graders the wrong replies a
model could really give, and check that each one is caught.
"""

from __future__ import annotations

import io
from typing import Any

import pytest
from PIL import Image
from sqlalchemy.orm import Session

from khazana.ai.evals.base import EvalCase
from khazana.ai.evals.logo_scenes import HEIGHT, SCENES, WIDTH, render
from khazana.ai.evals.run import report, run_suite
from khazana.ai.evals.suites.logo_detection import SUITE
from khazana.ai.logo_regions import (
    FULL_IMAGE,
    MIN_PADDING,
    Box,
    clip,
    coverage,
    pad,
    union_area,
)
from khazana.ai.schemas import LogoDetection

MARKED_SCENES = [name for name in SCENES if render(name).marks]
MUST_HIDE_SCENES = [name for name in MARKED_SCENES if name != "tone_on_tone_mark"]


def _case(name: str) -> EvalCase:
    return next(case for case in SUITE.cases if case.name == name)


def _reply(
    boxes: list[Box] | tuple[Box, ...] = (),
    *,
    readable: bool = True,
    review: bool = False,
    reason: str | None = None,
) -> dict[str, Any]:
    return {
        "regions": [
            {
                "kind": "logo",
                "x": box.x,
                "y": box.y,
                "width": box.width,
                "height": box.height,
                "confidence": 0.9,
            }
            for box in boxes
        ],
        "image_readable": readable,
        "needs_human_review": review,
        "review_reason": reason,
    }


def _passes(case: EvalCase, output: dict[str, Any]) -> bool:
    LogoDetection.model_validate(output)
    return all(grader(output).passed for grader in case.graders)


class TestGeometry:
    def test_padding_grows_a_box_on_every_side(self) -> None:
        padded = pad(Box(0.4, 0.4, 0.2, 0.1))
        assert padded.x == pytest.approx(0.34)
        assert padded.y == pytest.approx(0.37)
        assert padded.right == pytest.approx(0.66)
        assert padded.bottom == pytest.approx(0.53)

    def test_a_tiny_box_still_gets_the_minimum_margin(self) -> None:
        padded = pad(Box(0.5, 0.5, 0.001, 0.001))
        assert padded.x == pytest.approx(0.5 - MIN_PADDING)

    def test_padding_stays_inside_the_image(self) -> None:
        assert pad(Box(0.0, 0.0, 1.0, 1.0)) == FULL_IMAGE

    def test_a_box_outside_the_image_has_no_area(self) -> None:
        assert clip(Box(1.2, 0.2, 0.1, 0.1)).area == 0

    def test_overlapping_boxes_are_counted_once(self) -> None:
        boxes = [Box(0, 0, 0.5, 0.5), Box(0.25, 0, 0.5, 0.5)]
        assert union_area(boxes) == pytest.approx(0.375)

    def test_coverage_adds_up_across_boxes(self) -> None:
        mark = Box(0.2, 0.2, 0.4, 0.2)
        left = Box(0.2, 0.2, 0.2, 0.2)
        right = Box(0.4, 0.2, 0.1, 0.2)
        assert coverage(mark, [left, right]) == pytest.approx(0.75)


class TestScenes:
    @pytest.mark.parametrize("name", list(SCENES))
    def test_a_scene_is_a_real_jpeg_of_the_expected_size(self, name: str) -> None:
        with Image.open(io.BytesIO(render(name).jpeg)) as image:
            assert image.format == "JPEG"
            assert image.size == (WIDTH, HEIGHT)

    @pytest.mark.parametrize("name", MARKED_SCENES)
    def test_every_true_position_is_inside_the_image(self, name: str) -> None:
        for mark in render(name).marks:
            assert mark.area > 0
            assert mark.x >= 0
            assert mark.y >= 0
            assert mark.right <= 1
            assert mark.bottom <= 1

    def test_the_two_mark_scene_has_two_marks(self) -> None:
        assert len(render("two_marks_on_one_garment").marks) == 2

    def test_every_scene_has_a_case_and_its_own_prompt(self) -> None:
        assert {case.name for case in SUITE.cases} == set(SCENES)
        rendered = {tuple(case.prompt_values.items()) for case in SUITE.cases}
        assert len(rendered) == len(SUITE.cases), "cases would share one fixture"


class TestGradersCatchWrongReplies:
    @pytest.mark.parametrize("name", MARKED_SCENES)
    def test_the_true_positions_pass(self, name: str) -> None:
        review = name == "tone_on_tone_mark"
        output = _reply(render(name).marks, review=review, reason="Faint" if review else None)
        assert _passes(_case(name), output)

    @pytest.mark.parametrize("name", MUST_HIDE_SCENES)
    def test_finding_nothing_fails(self, name: str) -> None:
        assert not _passes(_case(name), _reply())

    @pytest.mark.parametrize("name", MUST_HIDE_SCENES)
    def test_asking_for_review_does_not_excuse_a_miss_on_a_clear_mark(self, name: str) -> None:
        output = _reply(review=True, reason="Could not tell")
        assert not _passes(_case(name), output)

    def test_finding_one_of_two_marks_fails(self) -> None:
        marks = render("two_marks_on_one_garment").marks
        assert not _passes(_case("two_marks_on_one_garment"), _reply(marks[:1]))

    def test_a_box_in_the_wrong_place_fails(self) -> None:
        mark = render("wordmark_on_chest").marks[0]
        wrong = Box(mark.x, min(mark.y + 0.4, 0.9), mark.width, mark.height)
        assert not _passes(_case("wordmark_on_chest"), _reply([wrong]))

    def test_a_box_covering_half_the_mark_fails(self) -> None:
        mark = render("printed_carton").marks[0]
        half = Box(mark.x, mark.y, mark.width / 3, mark.height)
        assert not _passes(_case("printed_carton"), _reply([half]))

    def test_blurring_the_whole_photograph_fails(self) -> None:
        assert not _passes(_case("wordmark_on_chest"), _reply([FULL_IMAGE]))

    def test_obeying_the_text_in_the_photograph_fails(self) -> None:
        assert not _passes(_case("instruction_on_garment"), _reply())

    def test_a_faint_mark_may_go_to_a_person(self) -> None:
        output = _reply(review=True, reason="A faint mark may be present")
        assert _passes(_case("tone_on_tone_mark"), output)

    def test_a_faint_mark_missed_in_silence_fails(self) -> None:
        assert not _passes(_case("tone_on_tone_mark"), _reply())

    def test_calling_an_unreadable_photograph_clean_fails(self) -> None:
        assert not _passes(_case("unreadable_photo"), _reply())

    def test_an_unreadable_photograph_needs_a_reason(self) -> None:
        output = _reply(readable=False, review=True)
        assert not _passes(_case("unreadable_photo"), output)

    def test_an_unreadable_photograph_sent_to_a_person_passes(self) -> None:
        output = _reply(readable=False, review=True, reason="Too dark to inspect")
        assert _passes(_case("unreadable_photo"), output)

    def test_naming_the_brand_in_the_reason_fails(self) -> None:
        scene = SCENES["wordmark_on_chest"]
        output = _reply(
            render(scene.name).marks,
            review=True,
            reason=f"This looks like {scene.brand_name.title()}",
        )
        assert not _passes(_case(scene.name), output)

    @pytest.mark.parametrize(
        "name",
        ["plain_garment", "striped_garment", "repeating_print", "care_label_without_brand"],
    )
    def test_a_large_blur_on_a_photograph_with_no_mark_fails(self, name: str) -> None:
        assert _passes(_case(name), _reply())
        assert not _passes(_case(name), _reply([Box(0.2, 0.2, 0.3, 0.3)]))


class TestOfflineRun:
    def test_the_suite_passes_on_its_committed_fixtures(self, db: Session) -> None:
        outcomes = run_suite(db, SUITE, record=False)
        assert [o.case.name for o in outcomes if not o.passed] == []
        assert report(SUITE, outcomes)

    def test_the_real_photograph_reaches_the_model_call(
        self, db: Session, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from khazana.ai.gateway import client

        sent: list[bytes] = []
        original = client.call_model

        def spy(**kwargs: Any) -> client.ModelReply:
            sent.extend(kwargs["images"])
            return original(**kwargs)

        monkeypatch.setattr(client, "call_model", spy)
        run_suite(db, SUITE, record=False)
        assert sent[0] == render(SUITE.cases[0].name).jpeg
