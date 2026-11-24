"""The daily markdown agent through the Message Batches API.

Submitted once a day, collected when the batch ends, priced at half the live
rate. Hours pass between the two, so every decision is checked against the
lot again before it is applied.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace
from typing import Any

import anthropic
import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from commerce_helpers import live_lot, make_courier, policy_for
from khazana.ai.gateway import client, cost
from khazana.config import get_settings
from khazana.models import AiJob, AiOutput, AuditLog, Lot
from khazana.models.enums import AiJobStatus, AiMode, LotStatus
from khazana.services import markdown_service

DECISION = {"reduce_by_percent": 5, "reason": "Nothing sold in 30 days."}


@pytest.fixture
def lot(db: Session, two_brands, category) -> Lot:  # type: ignore[no-untyped-def]
    (brand, owner), _ = two_brands
    make_courier(db)
    policy = policy_for(db, brand)
    policy.allow_auto_markdown = True
    policy.markdown_step_percent = Decimal(5)
    policy.markdown_interval_days = 14
    policy.markdown_floor_percent = Decimal(80)
    db.commit()
    lot = live_lot(db, brand, owner, category.id)
    lot.approved_at = datetime.now(UTC) - timedelta(days=30)
    db.commit()
    return lot


class _FakeBatches:
    def __init__(self) -> None:
        self.created: list[list[dict[str, Any]]] = []
        self.status = "in_progress"
        self.outcome = "succeeded"

    def create(self, *, requests: list[dict[str, Any]]) -> SimpleNamespace:
        self.created.append(requests)
        return SimpleNamespace(id=f"msgbatch_{len(self.created)}")

    def retrieve(self, batch_id: str) -> SimpleNamespace:
        return SimpleNamespace(processing_status=self.status)

    def results(self, batch_id: str) -> list[SimpleNamespace]:
        index = int(batch_id.rsplit("_", 1)[1]) - 1
        out = []
        for request in self.created[index]:
            message = SimpleNamespace(
                model=request["params"]["model"],
                stop_reason="end_turn",
                content=[SimpleNamespace(type="text", text=json.dumps(DECISION))],
                usage=SimpleNamespace(
                    input_tokens=1000,
                    output_tokens=100,
                    cache_read_input_tokens=0,
                    cache_creation_input_tokens=0,
                ),
            )
            out.append(
                SimpleNamespace(
                    custom_id=request["custom_id"],
                    result=SimpleNamespace(type=self.outcome, message=message),
                )
            )
        return out


@pytest.fixture
def batches(monkeypatch: pytest.MonkeyPatch) -> _FakeBatches:
    monkeypatch.setattr(get_settings(), "ai_offline", False)
    monkeypatch.setattr(get_settings(), "anthropic_api_key", "sk-test-not-real")
    fake = _FakeBatches()
    api = SimpleNamespace(messages=SimpleNamespace(batches=fake))
    monkeypatch.setattr(anthropic, "Anthropic", lambda **_: api)
    return fake


def test_offline_the_batch_answers_at_once(db: Session, lot: Lot, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(
        client,
        "call_model",
        lambda **_: client.ModelReply(
            content=DECISION,
            usage=client.Usage(),
            model="claude-haiku-5-5",
            latency_ms=0,
            from_fixture=True,
        ),
    )
    before = lot.lot_price_pkr
    results = markdown_service.submit_batch(db)
    assert [r.lot_id for r in results] == [lot.id]
    assert lot.lot_price_pkr < before
    job = db.scalars(select(AiJob)).one()
    assert job.mode == AiMode.OFFLINE
    assert (job.batch_id or "").startswith("offline-")


def test_a_live_batch_is_applied_when_it_ends_at_half_price(
    db: Session, lot: Lot, batches: _FakeBatches
) -> None:
    before = lot.lot_price_pkr
    assert markdown_service.submit_batch(db) == []
    job = db.scalars(select(AiJob)).one()
    assert (job.status, job.batch_id) == (AiJobStatus.RUNNING, "msgbatch_1")
    request = batches.created[0][0]
    assert request["custom_id"] == job.id
    assert "fallbacks" not in request["params"], "a batch request cannot carry a fallback"

    # Still running: nothing applied, and tomorrow's submit does not send it again.
    assert markdown_service.collect_batch(db) == []
    markdown_service.submit_batch(db, now=datetime.now(UTC) + timedelta(days=1))
    assert len(batches.created) == 1
    assert lot.lot_price_pkr == before

    batches.status = "ended"
    results = markdown_service.collect_batch(db)
    assert [r.lot_id for r in results] == [lot.id]
    db.refresh(lot)
    assert lot.lot_price_pkr < before
    db.refresh(job)
    assert (job.status, job.mode) == (AiJobStatus.SUCCEEDED, AiMode.BATCH)
    output = db.scalars(select(AiOutput)).one()
    usage = cost.Usage(input_tokens=1000, output_tokens=100)
    live_price = cost.price_call(output.model, usage, AiMode.LIVE)
    assert Decimal(str(output.cost_usd)) == live_price / 2
    assert db.scalars(select(AuditLog).where(AuditLog.action == "lot.marked_down")).first()


def test_a_lot_that_changed_while_the_batch_ran_is_left_alone(
    db: Session, lot: Lot, batches: _FakeBatches
) -> None:
    before = lot.lot_price_pkr
    markdown_service.submit_batch(db)
    lot.status = LotStatus.SOLD
    db.commit()
    batches.status = "ended"
    assert markdown_service.collect_batch(db) == []
    db.refresh(lot)
    assert lot.lot_price_pkr == before


def test_a_failed_request_marks_its_job_failed(
    db: Session, lot: Lot, batches: _FakeBatches
) -> None:
    markdown_service.submit_batch(db)
    batches.status = "ended"
    batches.outcome = "errored"
    assert markdown_service.collect_batch(db) == []
    job = db.scalars(select(AiJob)).one()
    assert job.status == AiJobStatus.FAILED
    assert "errored" in (job.error or "")
