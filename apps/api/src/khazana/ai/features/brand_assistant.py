"""The brand assistant.

Answers a brand's questions about its own stock and sales: what is slow, what
to discount, what sold where. Same two step shape as the buyer assistant, a
plan and then an answer, and the same guarantee: numbers come only from
lookups made in this turn.

The access boundary is in code, not in the prompt. The brand comes from the
session and is passed to every tool; the plan cannot name one. The answer
step is told it may only describe this brand's data, but nothing depends on
it obeying, because it was never given anything else.
"""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy.orm import Session

from ...models import Brand
from ...models.enums import AiFeature
from ..gateway import run_feature
from ..schemas import AssistantAnswer, BrandToolPlan
from ..tools import brand_tools, catalog_tools
from .assistant import NO_HISTORY, AssistantTurn, _clean_message, render_results

logger = logging.getLogger(__name__)

PLAN_PROMPT = "brand_plan"
ANSWER_PROMPT = "assistant_brand"
MAX_TOOL_CALLS = 5


def ask(
    db: Session,
    *,
    message: str,
    brand_id: str,
    user_id: str,
    history: str = "",
    record_fixture: bool = False,
) -> AssistantTurn:
    """Answer one question from a brand member about that brand."""
    cleaned = _clean_message(message)
    earlier = history.strip() or NO_HISTORY
    brand = db.get(Brand, brand_id)
    brand_name = brand.name if brand else "this brand"

    plan_result = run_feature(
        db,
        AiFeature.ASSISTANT_BRAND,
        prompt_name=PLAN_PROMPT,
        prompt_values={"message": cleaned, "brand_name": brand_name, "history": earlier},
        output_schema=BrandToolPlan,
        brand_id=brand_id,
        user_id=user_id,
        entity_type="brand_assistant_turn",
        record_fixture=record_fixture,
    )
    plan = plan_result.output
    assert isinstance(plan, BrandToolPlan)

    results, executed, rejected = execute_plan(db, plan, brand_id=brand_id)

    answer_result = run_feature(
        db,
        AiFeature.ASSISTANT_BRAND,
        prompt_name=ANSWER_PROMPT,
        prompt_values={
            "message": cleaned,
            "brand_name": brand_name,
            "today": catalog_tools.now_iso(),
            "tool_results": render_results(results),
            "history": earlier,
        },
        output_schema=AssistantAnswer,
        brand_id=brand_id,
        user_id=user_id,
        entity_type="brand_assistant_turn",
        record_fixture=record_fixture,
    )
    answer = answer_result.output
    assert isinstance(answer, AssistantAnswer)
    answer = answer.model_copy(update={"tool_calls_made": executed})

    return AssistantTurn(
        answer=answer,
        plan=plan,
        tool_results=results,
        plan_result=plan_result,
        answer_result=answer_result,
        rejected_calls=rejected,
    )


def execute_plan(
    db: Session, plan: BrandToolPlan, *, brand_id: str
) -> tuple[dict[str, Any], list[str], list[str]]:
    """Run the planned lookups for this brand. Unknown tools are dropped."""
    results: dict[str, Any] = {}
    executed: list[str] = []
    rejected: list[str] = []
    if plan.needs_no_tools:
        return results, executed, rejected

    for index, call in enumerate(plan.calls[:MAX_TOOL_CALLS]):
        if call.tool not in brand_tools.TOOLS:
            logger.warning("brand assistant planned an unknown tool %r, dropped", call.tool)
            rejected.append(call.tool)
            continue
        label = f"{call.tool}#{index + 1}"
        try:
            results[label] = brand_tools.run_tool(db, call.tool, call.arguments, brand_id=brand_id)
            executed.append(call.tool)
        except TypeError as exc:
            logger.info("brand tool %s rejected its arguments: %s", call.tool, exc)
            results[label] = {"error": "That lookup could not be run with those details."}
            rejected.append(call.tool)
        except Exception as exc:
            logger.exception("brand tool %s failed", call.tool)
            results[label] = {"error": f"The lookup failed: {type(exc).__name__}"}
            rejected.append(call.tool)
    return results, executed, rejected
