"""The Message Batches API, for AI work nobody is waiting for.

A batch runs at half the price of a live call and usually finishes within an
hour, at most within a day. The daily markdown agent is the job that fits:
the decision for a lot that has sat unsold for weeks can wait until the batch
comes back.

Two steps, because the reply arrives later:

1. ``submit`` renders every request, records one ``AiJob`` per item and sends
   them as one batch. The job id is each request's ``custom_id``.
2. ``collect`` reads every finished batch, validates each reply against the
   feature's schema, records it at the batch price and returns what finished,
   for the caller to apply.

Offline, ``submit`` answers each item from its recorded fixture at once and
returns the results, so development, the tests and CI run the same flow with
no network and no spend.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from ...config import get_settings
from ...core.errors import AppError
from ...models import AiJob
from ...models.base import utcnow
from ...models.enums import AiFeature, AiJobStatus, AiMode
from ..schemas import SCHEMA_BY_FEATURE
from . import client, cost, limits, prompts, router
from .service import _json_schema, _record

logger = logging.getLogger(__name__)

OFFLINE_PREFIX = "offline-"


@dataclass(slots=True)
class BatchItem:
    """One request in a batch, and what it is about."""

    prompt_name: str
    prompt_values: dict[str, Any]
    brand_id: str | None = None
    entity_type: str | None = None
    entity_id: str | None = None


@dataclass(slots=True)
class BatchResult:
    """A finished item: its job and the validated reply."""

    job: AiJob
    output: BaseModel


def _schema(feature: AiFeature) -> type[BaseModel]:
    schema = SCHEMA_BY_FEATURE.get(feature.value)
    if schema is None:
        raise ValueError(f"No output schema registered for {feature.value}.")
    return schema


def submit(db: Session, feature: AiFeature, items: list[BatchItem]) -> list[BatchResult]:
    """Send ``items`` as one batch. Returns results at once only when offline."""
    if not items:
        return []
    route = router.route_for(feature)
    schema = _schema(feature)
    schema_json = _json_schema(schema)
    settings = get_settings()

    jobs: list[tuple[AiJob, prompts.Prompt, str, str]] = []
    for item in items:
        job = AiJob(
            feature=feature,
            status=AiJobStatus.QUEUED,
            mode=AiMode.BATCH,
            entity_type=item.entity_type,
            entity_id=item.entity_id,
            brand_id=item.brand_id,
        )
        db.add(job)
        db.flush()
        try:
            limits.assert_within_budget(db, feature, item.brand_id)
        except AppError as exc:
            job.status = (
                AiJobStatus.SKIPPED_KILL_SWITCH
                if exc.code == "feature_disabled"
                else AiJobStatus.BLOCKED_BY_LIMIT
            )
            job.blocked_reason = exc.message
            job.finished_at = utcnow()
            continue
        prompt = prompts.load(item.prompt_name)
        job.prompt_ref = f"{prompt.name}.v{prompt.version}"
        jobs.append(
            (
                job,
                prompt,
                prompt.render_system(**item.prompt_values),
                prompt.render(**item.prompt_values),
            )
        )
    db.flush()
    if not jobs:
        db.commit()
        return []

    if settings.ai_offline:
        batch_id = f"{OFFLINE_PREFIX}{uuid.uuid4().hex}"
        results = []
        for job, prompt, system, user_text in jobs:
            job.batch_id = batch_id
            reply = client.call_model(
                model=route.model_id,
                system=system,
                user_text=user_text,
                output_schema=schema_json,
                effort=route.effort,
                max_tokens=route.max_tokens,
                cache_prefix=route.cache_prefix,
                feature=feature.value,
                prompt_name=prompt.name,
                prompt_version=prompt.version,
            )
            result = _finish(db, job, route, prompt, schema, reply, AiMode.OFFLINE)
            if result is not None:
                results.append(result)
        db.commit()
        return results

    import anthropic

    api = anthropic.Anthropic(api_key=settings.anthropic_api_key)
    requests = [
        {
            "custom_id": job.id,
            "params": client.build_request(
                model=route.model_id,
                system=system,
                user_text=user_text,
                output_schema=schema_json,
                images=[],
                effort=route.effort,
                max_tokens=route.max_tokens,
                cache_prefix=route.cache_prefix,
            ),
        }
        for job, _prompt, system, user_text in jobs
    ]
    created = api.messages.batches.create(requests=requests)  # type: ignore[arg-type]
    now = utcnow()
    for job, _prompt, _system, _user in jobs:
        job.batch_id = created.id
        job.status = AiJobStatus.RUNNING
        job.started_at = now
        job.attempts += 1
    db.commit()
    logger.info("submitted batch %s with %d %s requests", created.id, len(jobs), feature.value)
    return []


def pending_entities(db: Session, feature: AiFeature, entity_type: str) -> set[str]:
    """Entities with a batch request still out, so they are not sent twice."""
    rows = db.scalars(
        select(AiJob.entity_id).where(
            AiJob.feature == feature,
            AiJob.entity_type == entity_type,
            AiJob.status == AiJobStatus.RUNNING,
            AiJob.batch_id.is_not(None),
        )
    )
    return {entity for entity in rows if entity}


def collect(db: Session, feature: AiFeature) -> list[BatchResult]:
    """Record every reply from batches that have ended, and return them."""
    running = list(
        db.scalars(
            select(AiJob).where(
                AiJob.feature == feature,
                AiJob.status == AiJobStatus.RUNNING,
                AiJob.batch_id.is_not(None),
            )
        )
    )
    if not running:
        return []
    by_batch: dict[str, dict[str, AiJob]] = {}
    for job in running:
        by_batch.setdefault(str(job.batch_id), {})[job.id] = job

    import anthropic

    api = anthropic.Anthropic(api_key=get_settings().anthropic_api_key)
    route = router.route_for(feature)
    schema = _schema(feature)
    results: list[BatchResult] = []
    for batch_id, jobs in by_batch.items():
        if batch_id.startswith(OFFLINE_PREFIX):
            continue
        status = api.messages.batches.retrieve(batch_id).processing_status
        if status != "ended":
            continue
        for item in api.messages.batches.results(batch_id):
            if item.custom_id not in jobs:
                continue
            job = jobs.pop(item.custom_id)
            outcome = item.result
            if outcome.type != "succeeded":
                _fail(job, f"batch request {outcome.type}")
                continue
            message = outcome.message
            prompt = _prompt_for(job)
            try:
                reply = client.reply_from_message(message, model=route.model_id)
            except client.AiClientError as exc:
                _fail(job, exc.message)
                continue
            result = _finish(db, job, route, prompt, schema, reply, AiMode.BATCH)
            if result is not None:
                results.append(result)
        for job in jobs.values():
            _fail(job, "the batch ended without a result for this request")
    db.commit()
    return results


def _prompt_for(job: AiJob) -> prompts.Prompt:
    name, _, version = (job.prompt_ref or "").rpartition(".v")
    return prompts.load(name, int(version))


def _fail(job: AiJob, reason: str) -> None:
    job.status = AiJobStatus.FAILED
    job.error = reason[:2000]
    job.finished_at = utcnow()


def _finish(
    db: Session,
    job: AiJob,
    route: router.Route,
    prompt: prompts.Prompt,
    schema: type[BaseModel],
    reply: client.ModelReply,
    mode: AiMode,
) -> BatchResult | None:
    """Validate, price at the batch rate, record, and mark the job done."""
    job.mode = mode
    call_cost = cost.price_call(reply.model, reply.usage, mode)
    try:
        validated = schema.model_validate(reply.content)
    except ValidationError as exc:
        _record(
            db, job=job, route=route, prompt=prompt, reply=reply, call_cost=call_cost, output=None
        )
        cost.record_spend(db, feature=job.feature, brand_id=job.brand_id, cost_usd=call_cost)
        _fail(job, f"reply did not match schema: {exc.errors()[:3]}")
        return None
    _record(
        db,
        job=job,
        route=route,
        prompt=prompt,
        reply=reply,
        call_cost=call_cost,
        output=validated.model_dump(mode="json"),
    )
    cost.record_spend(db, feature=job.feature, brand_id=job.brand_id, cost_usd=Decimal(call_cost))
    job.status = AiJobStatus.SUCCEEDED
    job.finished_at = utcnow()
    return BatchResult(job=job, output=validated)
