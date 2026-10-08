"""Eval primitives.

An AI feature without an eval is a demo. The roadmap makes the eval a
precondition for building the feature, and this module is what the suites are
written against.

Design choices worth defending:

- Graders are plain functions returning a pass, a fail and a reason. No
  framework, because a grader you cannot read is a grader you cannot trust.
- Suites are small and fixed. Every run of a live suite costs real money, so
  twenty well chosen cases beat two thousand generated ones.
- A case can be marked ``must_pass``. Those are the rules that are not
  allowed to regress, for example the assistant refusing to quote a price it
  did not look up. A failure in one of those fails the whole run.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Any

from ...models.enums import AiFeature


@dataclass(frozen=True, slots=True)
class GradeResult:
    passed: bool
    reason: str = ""


Grader = Callable[[dict[str, Any]], GradeResult]


@dataclass(frozen=True, slots=True)
class EvalCase:
    """One input, and what a good answer looks like."""

    name: str
    prompt_values: dict[str, Any]
    graders: Sequence[Grader]
    images: int = 0
    # A case that encodes a rule rather than a quality target. Regressions
    # here fail the build.
    must_pass: bool = False
    note: str = ""


@dataclass(frozen=True, slots=True)
class EvalSuite:
    feature: AiFeature
    prompt_name: str
    cases: Sequence[EvalCase]
    # The share of non mandatory cases that must pass for the suite to pass.
    pass_threshold: float = 0.8


@dataclass(slots=True)
class CaseOutcome:
    case: EvalCase
    passed: bool
    reasons: list[str] = field(default_factory=list)
    cost_usd: float = 0.0
    error: str | None = None


# ----------------------------------------------------------------- graders
# Small, composable, and each one explains its own failure.


def field_equals(path: str, expected: Any) -> Grader:
    def grade(output: dict[str, Any]) -> GradeResult:
        actual = _dig(output, path)
        if actual == expected:
            return GradeResult(True)
        return GradeResult(False, f"{path} was {actual!r}, expected {expected!r}")

    return grade


def field_in(path: str, allowed: Sequence[Any]) -> Grader:
    def grade(output: dict[str, Any]) -> GradeResult:
        actual = _dig(output, path)
        if actual in allowed:
            return GradeResult(True)
        return GradeResult(False, f"{path} was {actual!r}, expected one of {list(allowed)!r}")

    return grade


def field_between(path: str, low: float, high: float) -> Grader:
    def grade(output: dict[str, Any]) -> GradeResult:
        actual = _dig(output, path)
        if isinstance(actual, (int, float)) and low <= actual <= high:
            return GradeResult(True)
        return GradeResult(False, f"{path} was {actual!r}, expected between {low} and {high}")

    return grade


def list_contains(path: str, item: Any) -> Grader:
    def grade(output: dict[str, Any]) -> GradeResult:
        actual = _dig(output, path)
        if isinstance(actual, list) and item in actual:
            return GradeResult(True)
        return GradeResult(False, f"{path} did not contain {item!r}, it was {actual!r}")

    return grade


def list_non_empty(path: str) -> Grader:
    def grade(output: dict[str, Any]) -> GradeResult:
        actual = _dig(output, path)
        if isinstance(actual, list) and actual:
            return GradeResult(True)
        return GradeResult(False, f"{path} was empty")

    return grade


def text_excludes(path: str, forbidden: Sequence[str]) -> Grader:
    """Fail if any forbidden substring appears, case insensitively.

    Used for the rules that are about what a model must not say: marketing
    language in a trade listing, a price it was told not to state, or an
    accusation in a risk finding.
    """

    def grade(output: dict[str, Any]) -> GradeResult:
        actual = str(_dig(output, path) or "").lower()
        hits = [word for word in forbidden if word.lower() in actual]
        if not hits:
            return GradeResult(True)
        return GradeResult(False, f"{path} contained forbidden wording: {hits}")

    return grade


def custom(fn: Callable[[dict[str, Any]], GradeResult]) -> Grader:
    return fn


def _dig(output: dict[str, Any], path: str) -> Any:
    node: Any = output
    for part in path.split("."):
        if isinstance(node, dict):
            node = node.get(part)
        else:
            return None
    return node
