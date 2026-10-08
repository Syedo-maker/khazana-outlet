"""The gateway entry point.

Every AI feature in the platform calls ``run_feature``. Nothing else
constructs a client, picks a model, or writes a cost row.

What one call does, in order:

1. Checks the kill switch and the spend caps, before any money is spent.
2. Creates an ``AiJob`` row, so the attempt is recorded even if it fails.
3. Loads the versioned prompt and renders the variable part.
4. Calls the model, live or from a fixture.
5. Validates the reply against the feature's schema.
6. Prices the call from the returned token counts and records the spend.
7. Stores the output, ready for a human to accept or correct.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, TypeVar

from pydantic import BaseModel, ValidationError
from sqlalchemy.orm import Session

from ...core.errors import AppError, ValidationFailed
from ...models import AiJob, AiOutput
from ...models.base import utcnow
from ...models.enums import AiFeature, AiJobStatus, AiMode
from ..schemas import SCHEMA_BY_FEATURE
from . import client, cost, limits, prompts, router

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)


@dataclass(slots=True)
class AiResult:
    """What a feature returns to its caller."""

    output: BaseModel
    job_id: str
    output_id: str
    model: str
    cost_usd: Decimal
    latency_ms: int
    from_fixture: bool

    @property
    def cost_pkr_estimate(self) -> str:
        """Deliberately a string with a caveat, not a number.

        There is no exchange rate hard coded anywhere in this codebase. A
        stale rate in source is worse than no rate, so the interface shows
        dollars and converts at display time if it must.
        """
        return f"{self.cost_usd} USD"


def run_feature(
    db: Session,
    feature: AiFeature,
    *,
    prompt_name: str,
    prompt_values: dict[str, Any],
    images: list[bytes] | None = None,
    brand_id: str | None = None,
    user_id: str | None = None,
    entity_type: str | None = None,
    entity_id: str | None = None,
    prompt_version: int | None = None,
    record_fixture: bool = False,
) -> AiResult:
    route = router.route_for(feature)
    images = images or []

    job = AiJob(
        feature=feature,
        status=AiJobStatus.QUEUED,
        mode=route.mode,
        entity_type=entity_type,
        entity_id=entity_id,
        brand_id=brand_id,
        requested_by_user_id=user_id,
    )
    db.add(job)
    db.flush()

    # Guards first. A blocked job keeps its row so that throttling is visible
    # rather than looking like the feature simply did nothing.
    try:
        limits.assert_within_budget(db, feature, brand_id)
    except AppError as exc:
        job.status = (
            AiJobStatus.SKIPPED_KILL_SWITCH
            if exc.code == "feature_disabled"
            else AiJobStatus.BLOCKED_BY_LIMIT
        )
        job.blocked_reason = exc.message
        job.finished_at = utcnow()
        db.commit()
        raise

    prompt = prompts.load(prompt_name, prompt_version)
    user_text = prompt.render(**prompt_values)

    job.status = AiJobStatus.RUNNING
    job.started_at = utcnow()
    job.attempts += 1
    db.flush()

    schema_model = SCHEMA_BY_FEATURE.get(feature.value)
    if schema_model is None:
        raise ValidationFailed(
            f"No output schema registered for {feature.value}. Add one to "
            "ai/schemas.py so replies are validated rather than trusted."
        )

    try:
        reply = client.call_model(
            model=route.model_id,
            system=prompt.system,
            user_text=user_text,
            output_schema=_json_schema(schema_model),
            images=images,
            effort=route.effort,
            max_tokens=route.max_tokens,
            cache_prefix=route.cache_prefix,
            feature=feature.value,
            prompt_name=prompt.name,
            prompt_version=prompt.version,
            record=record_fixture,
        )
    except Exception as exc:
        job.status = AiJobStatus.FAILED
        job.error = str(exc)[:2000]
        job.finished_at = utcnow()
        db.commit()
        logger.exception("ai feature failed feature=%s job=%s", feature.value, job.id)
        raise

    call_cost = cost.price_call(
        reply.model, reply.usage, AiMode.OFFLINE if reply.from_fixture else route.mode
    )

    try:
        validated = schema_model.model_validate(reply.content)
    except ValidationError as exc:
        # The spend is recorded even when validation fails. The call was made
        # and the money was spent; hiding that would make the ledger lie.
        _record(
            db,
            job=job,
            route=route,
            prompt=prompt,
            reply=reply,
            call_cost=call_cost,
            output=None,
        )
        job.status = AiJobStatus.FAILED
        job.error = f"reply did not match schema: {exc.errors()[:3]}"
        job.finished_at = utcnow()
        cost.record_spend(db, feature=feature, brand_id=brand_id, cost_usd=call_cost)
        db.commit()
        raise ValidationFailed(
            "The model returned a reply that did not match the expected shape. "
            "The attempt and its cost have been recorded."
        ) from exc

    output_row = _record(
        db,
        job=job,
        route=route,
        prompt=prompt,
        reply=reply,
        call_cost=call_cost,
        output=validated.model_dump(mode="json"),
    )

    cost.record_spend(db, feature=feature, brand_id=brand_id, cost_usd=call_cost)
    job.status = AiJobStatus.SUCCEEDED
    job.finished_at = utcnow()
    db.commit()

    return AiResult(
        output=validated,
        job_id=job.id,
        output_id=output_row.id,
        model=reply.model,
        cost_usd=call_cost,
        latency_ms=reply.latency_ms,
        from_fixture=reply.from_fixture,
    )


def accept_output(
    db: Session,
    output_id: str,
    *,
    user_id: str,
    corrected: dict[str, Any] | None = None,
) -> AiOutput:
    """Record what the human did with the draft.

    This is the whole quality loop. ``accepted`` with no correction means the
    draft was good; a correction is a labelled example of the model being
    wrong. Phase 4 reads these to measure accuracy per field, and Phase 6
    onwards they are the training corpus.
    """
    row = db.get(AiOutput, output_id)
    if row is None:
        from ...core.errors import NotFound

        raise NotFound("That AI output does not exist.")

    row.accepted = corrected is None
    row.human_corrected = corrected
    row.reviewed_by_user_id = user_id
    row.reviewed_at = utcnow()
    db.commit()
    return row


def _record(
    db: Session,
    *,
    job: AiJob,
    route: router.Route,
    prompt: prompts.Prompt,
    reply: client.ModelReply,
    call_cost: Decimal,
    output: dict[str, Any] | None,
) -> AiOutput:
    row = AiOutput(
        job_id=job.id,
        model=reply.model,
        prompt_name=prompt.name,
        prompt_version=prompt.version,
        effort=route.effort,
        input_tokens=reply.usage.input_tokens,
        output_tokens=reply.usage.output_tokens,
        cache_read_tokens=reply.usage.cache_read_tokens,
        cache_write_tokens=reply.usage.cache_write_tokens,
        cost_usd=call_cost,
        latency_ms=reply.latency_ms,
        output=output,
    )
    db.add(row)
    db.flush()
    return row


def _json_schema(model: type[BaseModel]) -> dict[str, Any]:
    """Build the output schema the API constrains the reply to.

    ``additionalProperties: false`` plus a full ``required`` list is what makes
    a strict schema actually strict, and Pydantic does not add the former by
    default for every nested object.
    """
    schema = model.model_json_schema()

    def _tighten(node: Any) -> None:
        if isinstance(node, dict):
            if node.get("type") == "object":
                node.setdefault("additionalProperties", False)
            for value in node.values():
                _tighten(value)
        elif isinstance(node, list):
            for item in node:
                _tighten(item)

    _tighten(schema)
    return {"type": "json_schema", "schema": schema, "name": model.__name__}
