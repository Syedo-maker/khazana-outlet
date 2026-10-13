"""The buyer assistant.

Answers a shopkeeper's question in English, Urdu or Roman Urdu, using only
facts read from the database in this turn.

Shape of a turn, and why it is this shape:

1. **Plan.** One structured call picks which tools to run.
2. **Execute.** Code runs them, with the buyer identity injected from the
   session rather than taken from anything the model produced.
3. **Answer.** One structured call writes the reply, given the tool results
   and nothing else.

That is two model calls rather than a native tool use loop. The reasons are
practical: both calls are ordinary structured outputs so the existing gateway
handles them unchanged, each step can be evaluated on its own, and the cost of
a turn is bounded at two calls instead of however many a loop decides to make.
The trade is that the model cannot react to one tool result by calling another
tool in the same turn, which a follow up question handles. Native tool use is
the Phase 4 upgrade, once usage data shows where one round is not enough.

The guarantee this module exists to provide: the answer step is given tool
results and nothing else, every tool applies visibility itself, and a reply
that claims a fact with no tool behind it is caught by the eval.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.orm import Session

from ...core.errors import ValidationFailed
from ...models.enums import AiFeature
from ..gateway import AiResult, run_feature
from ..schemas import AssistantAnswer, ToolPlan
from ..tools import catalog_tools

logger = logging.getLogger(__name__)

PLAN_PROMPT = "assistant_plan"
ANSWER_PROMPT = "assistant_buyer"

MAX_MESSAGE_CHARS = 1_500
MAX_TOOL_CALLS = 6
# A tool result goes back into the model's context and is paid for per token,
# so the rendered block is capped. A truncated result is better than a bill
# that scales with how much stock a search happened to match.
MAX_TOOL_RESULT_CHARS = 6_000

KNOWN_TOOLS = {schema["name"] for schema in catalog_tools.TOOL_SCHEMAS}


@dataclass(slots=True)
class AssistantTurn:
    answer: AssistantAnswer
    plan: ToolPlan
    tool_results: dict[str, Any]
    plan_result: AiResult
    answer_result: AiResult
    rejected_calls: list[str] = field(default_factory=list)

    @property
    def total_cost_usd(self) -> Any:
        return self.plan_result.cost_usd + self.answer_result.cost_usd

    @property
    def is_grounded(self) -> bool:
        """Whether every factual claim could have come from a lookup.

        A reply that declines, or that made at least one tool call, is
        grounded. A confident answer with no tool call behind it is the exact
        failure this feature is built to prevent, so it is surfaced rather
        than assumed away.
        """
        if self.answer.declined:
            return True
        return bool(self.answer.tool_calls_made)


def ask(
    db: Session,
    *,
    message: str,
    buyer_user_id: str,
    buyer_city: str = "",
    record_fixture: bool = False,
) -> AssistantTurn:
    """Answer one buyer message."""
    cleaned = _clean_message(message)

    plan_result = run_feature(
        db,
        AiFeature.ASSISTANT_BUYER,
        prompt_name=PLAN_PROMPT,
        prompt_values={"message": cleaned, "buyer_city": buyer_city or "not given"},
        output_schema=ToolPlan,
        user_id=buyer_user_id,
        entity_type="assistant_turn",
        record_fixture=record_fixture,
    )
    plan = plan_result.output
    assert isinstance(plan, ToolPlan)

    results, executed, rejected = execute_plan(db, plan, buyer_user_id=buyer_user_id)

    answer_result = run_feature(
        db,
        AiFeature.ASSISTANT_BUYER,
        prompt_name=ANSWER_PROMPT,
        prompt_values={
            "message": cleaned,
            "buyer_city": buyer_city or "not given",
            "today": catalog_tools.now_iso(),
            "tool_results": render_results(results),
        },
        output_schema=AssistantAnswer,
        user_id=buyer_user_id,
        entity_type="assistant_turn",
        record_fixture=record_fixture,
    )
    answer = answer_result.output
    assert isinstance(answer, AssistantAnswer)

    # The model reports which tools it used. The record of what actually ran
    # is authoritative, because that is the list the grounding check and the
    # eval are judged against.
    answer = answer.model_copy(update={"tool_calls_made": executed})

    if not answer.declined and not executed:
        logger.warning("assistant answered with no tool call behind it, buyer=%s", buyer_user_id)

    return AssistantTurn(
        answer=answer,
        plan=plan,
        tool_results=results,
        plan_result=plan_result,
        answer_result=answer_result,
        rejected_calls=rejected,
    )


def execute_plan(
    db: Session, plan: ToolPlan, *, buyer_user_id: str
) -> tuple[dict[str, Any], list[str], list[str]]:
    """Run the planned tools. Returns results, what ran, and what was refused.

    A plan is a model output, so it is validated rather than trusted: an
    unknown tool name is dropped, the call count is capped, and a failing tool
    becomes an error entry instead of taking the turn down.
    """
    results: dict[str, Any] = {}
    executed: list[str] = []
    rejected: list[str] = []

    if plan.needs_no_tools:
        return results, executed, rejected

    for index, call in enumerate(plan.calls[:MAX_TOOL_CALLS]):
        if call.tool not in KNOWN_TOOLS:
            logger.warning("assistant planned an unknown tool %r, dropped", call.tool)
            rejected.append(call.tool)
            continue

        label = f"{call.tool}#{index + 1}"
        try:
            results[label] = catalog_tools.run_tool(
                db, call.tool, call.arguments, buyer_user_id=buyer_user_id
            )
            executed.append(call.tool)
        except TypeError as exc:
            # Wrong or missing arguments for that tool. Recoverable: the answer
            # step is told the lookup failed rather than being handed nothing
            # and left to guess.
            logger.info("assistant tool %s rejected its arguments: %s", call.tool, exc)
            results[label] = {"error": "That lookup could not be run with those details."}
            rejected.append(call.tool)
        # One bad tool must not lose the whole turn.
        except Exception as exc:
            logger.exception("assistant tool %s failed", call.tool)
            results[label] = {"error": f"The lookup failed: {type(exc).__name__}"}
            rejected.append(call.tool)

    return results, executed, rejected


def render_results(results: dict[str, Any]) -> str:
    """Format tool results for the answer prompt.

    An empty block says so explicitly rather than being blank. A blank section
    reads to a model like an omission it should fill in, which is the opposite
    of what is wanted here.
    """
    if not results:
        return (
            "No lookups were run for this message. You therefore know nothing "
            "about stock, prices, availability or orders, and must say so rather "
            "than answer from memory."
        )

    blocks = []
    for label, value in results.items():
        rendered = json.dumps(value, ensure_ascii=False, indent=2, default=str)
        if len(rendered) > MAX_TOOL_RESULT_CHARS:
            rendered = rendered[:MAX_TOOL_RESULT_CHARS] + "\n... (truncated)"
        blocks.append(f"### {label}\n{rendered}")
    return "\n\n".join(blocks)


def _clean_message(message: str) -> str:
    text = " ".join((message or "").split())
    if not text:
        raise ValidationFailed("Type a question first.")
    return text[:MAX_MESSAGE_CHARS]
