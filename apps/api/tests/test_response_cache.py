"""An identical request is answered from the stored reply, at no cost.

Only routes with ``response_cache_hours`` use it. The key covers the brand,
so one brand's answer never reaches another, and the image bytes, so one
photograph never gets another's listing.
"""

from __future__ import annotations

import json
from datetime import timedelta
from decimal import Decimal
from types import SimpleNamespace
from typing import Any

import anthropic
import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from khazana.ai.gateway import response_cache, router, run_feature
from khazana.ai.gateway.models import HAIKU_4_5
from khazana.config import get_settings
from khazana.models import AiJob, AiResponseCache
from khazana.models.base import utcnow
from khazana.models.enums import AiFeature, AiMode

RISK = {
    "score": 12,
    "findings": [],
    "completeness": 95,
    "manifest_consistent": True,
    "price_plausible": True,
    "counterfeit_signals": [],
    "recommend_human_review": False,
}
VALUES = {
    "manifest_total": 100,
    "declared_total": 100,
    "discount_percent": 75,
    "photo_count": 4,
    "condition_grade": "A",
    "defect_count": 0,
    "title": "Test lot",
    "description": "A plain factual description.",
    "category_slug": "womenswear-stitched",
}


@pytest.fixture
def api(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    """A fake live API that answers every call with a valid risk score."""
    monkeypatch.setattr(get_settings(), "ai_offline", False)
    monkeypatch.setattr(get_settings(), "anthropic_api_key", "sk-test-not-real")
    calls: list[dict[str, Any]] = []

    def create(**kwargs: Any) -> SimpleNamespace:
        calls.append(kwargs)
        return SimpleNamespace(
            model=kwargs["model"],
            stop_reason="end_turn",
            content=[SimpleNamespace(type="text", text=json.dumps(RISK))],
            usage=SimpleNamespace(
                input_tokens=900,
                output_tokens=120,
                cache_read_input_tokens=700,
                cache_creation_input_tokens=0,
            ),
        )

    messages = SimpleNamespace(create=create)
    fake = SimpleNamespace(messages=messages, beta=SimpleNamespace(messages=messages))
    monkeypatch.setattr(anthropic, "Anthropic", lambda **_: fake)
    return calls


def _score(db: Session, brand_id: str, **values: object):  # type: ignore[no-untyped-def]
    return run_feature(
        db,
        AiFeature.RISK_SCORING,
        prompt_name="risk_scoring",
        prompt_values={**VALUES, **values},
        brand_id=brand_id,
        entity_type="lot",
        entity_id="lot-1",
    )


def test_the_same_request_twice_is_paid_for_once(db: Session, api, two_brands) -> None:  # type: ignore[no-untyped-def]
    (brand, _), _ = two_brands
    first = _score(db, brand.id)
    second = _score(db, brand.id)
    assert len(api) == 1
    assert second.cost_usd == Decimal(0)
    assert second.output.model_dump() == first.output.model_dump()
    modes = [job.mode for job in db.scalars(select(AiJob).order_by(AiJob.created_at))]
    assert modes == [AiMode.LIVE, AiMode.CACHED]
    assert db.scalars(select(AiResponseCache)).one().hits == 1


def test_a_different_input_or_another_brand_is_a_new_call(db: Session, api, two_brands) -> None:  # type: ignore[no-untyped-def]
    (brand, _), (other, _) = two_brands
    _score(db, brand.id)
    _score(db, brand.id, title="Another lot")
    _score(db, other.id)
    assert len(api) == 3, "a changed input and another brand each pay for their own answer"


def test_an_expired_entry_is_called_again(db: Session, api, two_brands) -> None:  # type: ignore[no-untyped-def]
    (brand, _), _ = two_brands
    _score(db, brand.id)
    row = db.scalars(select(AiResponseCache)).one()
    row.expires_at = utcnow() - timedelta(minutes=1)
    db.commit()
    _score(db, brand.id)
    assert len(api) == 2
    assert response_cache.purge_expired(db) == 0, "the second call refreshed the entry"


def test_a_stored_reply_that_no_longer_validates_is_never_served(
    db: Session, api, two_brands
) -> None:  # type: ignore[no-untyped-def]
    (brand, _), _ = two_brands
    _score(db, brand.id)
    row = db.scalars(select(AiResponseCache)).one()
    row.output = {"score": "not a number"}
    db.commit()
    result = _score(db, brand.id)
    assert len(api) == 2
    assert result.output.score == 12  # type: ignore[attr-defined]


def test_conversational_features_never_use_it() -> None:
    for feature in (
        AiFeature.ASSISTANT_BUYER,
        AiFeature.ASSISTANT_BRAND,
        AiFeature.BARGAINING,
        AiFeature.RESELL_KIT,
        AiFeature.MARKDOWN,
    ):
        assert router.route_for(feature).response_cache_hours == 0, feature


def test_offline_fixtures_are_never_stored(db: Session, two_brands, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    from khazana.ai.gateway import client

    (brand, _), _ = two_brands
    monkeypatch.setattr(
        client,
        "call_model",
        lambda **_: client.ModelReply(
            content=RISK, usage=client.Usage(), model=HAIKU_4_5, latency_ms=0, from_fixture=True
        ),
    )
    _score(db, brand.id)
    assert db.scalars(select(AiResponseCache)).first() is None
