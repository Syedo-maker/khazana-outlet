"""The contract between prompts, the values code sends, and the schemas sent.

Three mistakes reached a live call before, each invisible offline: a prompt
placeholder never filled in, a schema keyword the structured output API
rejects, and a cost recorded at the wrong rate. These tests catch the first two
for every prompt and every schema actually sent, and pin the third.
"""

from __future__ import annotations

import re

import pytest

from khazana.ai.evals.run import discover_suites
from khazana.ai.gateway import prompts
from khazana.ai.gateway.service import _has_open_object, _json_schema
from khazana.ai.schemas import SCHEMA_BY_FEATURE, BrandToolPlan, ToolPlan

LEFTOVER = re.compile(r"\{[a-z_]+\}")
REJECTED = {
    "minimum",
    "maximum",
    "exclusiveMinimum",
    "exclusiveMaximum",
    "minLength",
    "maxLength",
    "maxItems",
    "minItems",
}
# Per call values in a system part defeat the prompt cache, because the cached
# prefix then differs on every call. Allowed only where the value is stable for
# a whole deployment, like the category taxonomy.
STABLE_SYSTEM_VALUES = {"listing_from_photos": {"category_list"}}

SUITES = discover_suites(None)


@pytest.mark.parametrize("suite", SUITES, ids=lambda s: s.prompt_name)
def test_every_case_renders_with_nothing_left_unfilled(suite) -> None:  # type: ignore[no-untyped-def]
    prompt = prompts.load(suite.prompt_name)
    for case in suite.cases:
        system = prompt.render_system(**case.prompt_values)
        user = prompt.render(**case.prompt_values)
        left = set(LEFTOVER.findall(system)) | set(LEFTOVER.findall(user))
        assert not left, f"{suite.prompt_name} {case.name} left {sorted(left)} unfilled"


@pytest.mark.parametrize("name", sorted(prompts.all_prompts()))
def test_system_parts_hold_no_per_call_values(name: str) -> None:
    prompt = prompts.load(name)
    found = {match.strip("{}") for match in LEFTOVER.findall(prompt.system)}
    allowed = STABLE_SYSTEM_VALUES.get(name, set())
    assert found <= allowed, f"{name} has per call values in its system part: {found - allowed}"


SENT_SCHEMAS = {**SCHEMA_BY_FEATURE, "assistant_plan": ToolPlan, "brand_plan": BrandToolPlan}


def _keywords(node: object) -> set[str]:
    if isinstance(node, dict):
        found = REJECTED & set(node)
        for key, value in node.items():
            if key == "properties" and isinstance(value, dict):
                found.update(k for v in value.values() for k in _keywords(v))
            else:
                found |= _keywords(value)
        return found
    if isinstance(node, list):
        return {k for item in node for k in _keywords(item)}
    return set()


@pytest.mark.parametrize("name", sorted(SENT_SCHEMAS))
def test_every_schema_actually_sent_is_one_the_api_accepts(name: str) -> None:
    built = _json_schema(SENT_SCHEMAS[name])["schema"]
    assert not _has_open_object(built), f"{name} has an open object"
    assert not _keywords(built), f"{name} sends {sorted(_keywords(built))}"


def test_a_job_records_the_mode_it_ran_in_not_the_routes_intent(db) -> None:  # type: ignore[no-untyped-def]
    """Markdown routes as batch but runs live; the job must not claim batch."""
    from khazana.ai.gateway import run_feature
    from khazana.ai.schemas import MarkdownDecision
    from khazana.models import AiJob
    from khazana.models.enums import AiFeature, AiMode

    suite = next(s for s in SUITES if s.prompt_name == "markdown")
    run_feature(
        db,
        AiFeature.MARKDOWN,
        prompt_name="markdown",
        prompt_values=suite.cases[0].prompt_values,
        output_schema=MarkdownDecision,
    )
    job = db.query(AiJob).one()
    assert job.mode == AiMode.OFFLINE
