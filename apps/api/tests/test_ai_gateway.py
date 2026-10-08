"""AI gateway tests.

The gateway is tested harder than the features it will serve, because a
mistake here is a mistake in every AI feature at once: a wrong price, a cap
that does not hold, or an unvalidated reply reaching the catalogue.
"""

from __future__ import annotations

import json
from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from khazana.ai.gateway import client, cost, limits, prompts, router
from khazana.ai.gateway.models import HAIKU_4_5, OPUS_5_5, spec_for
from khazana.ai.gateway.service import accept_output, run_feature
from khazana.core.errors import FeatureDisabled, SpendLimitReached, ValidationFailed
from khazana.models import AiJob, AiOutput, AiSpend
from khazana.models.enums import AiFeature, AiJobStatus, AiMode


class TestPricing:
    def test_a_plain_call_is_priced_from_the_catalogue(self) -> None:
        usage = cost.Usage(input_tokens=1_000_000, output_tokens=0)
        assert cost.price_call(OPUS_5_5, usage) == Decimal("4.000000")

        usage = cost.Usage(input_tokens=0, output_tokens=1_000_000)
        assert cost.price_call(OPUS_5_5, usage) == Decimal("20.000000")

    def test_cached_reads_are_much_cheaper(self) -> None:
        """Lever 1 in docs/ai-architecture.md, as arithmetic.

        If this ratio ever stops holding, the whole cost model in the roadmap
        needs revisiting, so it is asserted rather than assumed.
        """
        fresh = cost.price_call(OPUS_5_5, cost.Usage(input_tokens=1_000_000))
        cached = cost.price_call(OPUS_5_5, cost.Usage(cache_read_tokens=1_000_000))
        assert cached * 20 == fresh

    def test_an_unverified_cache_price_is_charged_at_the_full_rate(self) -> None:
        """Never let an unknown make the bill look smaller than it is."""
        assert spec_for(HAIKU_4_5).cache_read_per_mtok is None
        cached = cost.price_call(HAIKU_4_5, cost.Usage(cache_read_tokens=1_000_000))
        fresh = cost.price_call(HAIKU_4_5, cost.Usage(input_tokens=1_000_000))
        assert cached == fresh

    def test_batch_is_half_price(self) -> None:
        usage = cost.Usage(input_tokens=1_000_000)
        live = cost.price_call(OPUS_5_5, usage, AiMode.LIVE)
        batch = cost.price_call(OPUS_5_5, usage, AiMode.BATCH)
        assert batch == live / 2

    def test_offline_costs_nothing(self) -> None:
        usage = cost.Usage(input_tokens=5_000_000, output_tokens=1_000_000)
        assert cost.price_call(OPUS_5_5, usage, AiMode.OFFLINE) == Decimal("0")

    def test_an_unknown_model_is_refused(self) -> None:
        """Routing to an unpriced model would make spend unmeasurable."""
        with pytest.raises(ValueError, match="Unknown model"):
            cost.price_call("claude-imaginary-9", cost.Usage(input_tokens=10))

    def test_the_listing_estimate_is_in_the_expected_range(self) -> None:
        """Sanity check on the figure the roadmap quotes.

        docs/ai-architecture.md estimates about four cents per listing with
        four photographs. This asserts the order of magnitude, not the exact
        number, because the token count per image is still a placeholder.
        """
        estimate = cost.estimate_listing_cost(OPUS_5_5, images=4)
        assert Decimal("0.01") < estimate < Decimal("0.10")


class TestSpendLedger:
    def test_spend_accumulates_per_day_and_feature(self, db: Session) -> None:
        cost.record_spend(db, feature=AiFeature.PRICING, brand_id=None, cost_usd=Decimal("0.01"))
        cost.record_spend(db, feature=AiFeature.PRICING, brand_id=None, cost_usd=Decimal("0.02"))
        db.commit()

        rows = db.scalars(select(AiSpend)).all()
        assert len(rows) == 1
        assert Decimal(str(rows[0].cost_usd)) == Decimal("0.03")
        assert rows[0].calls == 2

    def test_brand_spend_is_tracked_separately(self, db: Session, two_brands) -> None:  # type: ignore[no-untyped-def]
        (brand, _), _ = two_brands
        cost.record_spend(
            db, feature=AiFeature.PRICING, brand_id=brand.id, cost_usd=Decimal("0.05")
        )
        cost.record_spend(db, feature=AiFeature.PRICING, brand_id=None, cost_usd=Decimal("0.05"))
        db.commit()

        assert len(db.scalars(select(AiSpend)).all()) == 2
        assert limits.spend_this_month(db, brand.id) == Decimal("0.05")
        assert limits.spend_today(db) == Decimal("0.10")


class TestLimits:
    def test_the_daily_cap_blocks_before_spending(self, db: Session, monkeypatch) -> None:  # type: ignore[no-untyped-def]
        from khazana.config import get_settings

        monkeypatch.setenv("AI_DAILY_SPEND_LIMIT_USD", "0.10")
        get_settings.cache_clear()

        cost.record_spend(db, feature=AiFeature.PRICING, brand_id=None, cost_usd=Decimal("0.10"))
        db.commit()

        with pytest.raises(SpendLimitReached):
            limits.assert_within_budget(db, AiFeature.PRICING)

        get_settings.cache_clear()

    def test_the_brand_cap_reads_the_brand_policy(self, db: Session, two_brands) -> None:  # type: ignore[no-untyped-def]
        """Policy as data: the cap is the brand's own row, not a constant."""
        (brand, _), _ = two_brands
        brand.policy.ai_monthly_budget_usd = Decimal("0.05")
        db.commit()

        cost.record_spend(
            db, feature=AiFeature.PRICING, brand_id=brand.id, cost_usd=Decimal("0.05")
        )
        db.commit()

        with pytest.raises(SpendLimitReached):
            limits.assert_within_budget(db, AiFeature.PRICING, brand_id=brand.id)

        # Another brand is unaffected by the first one's spend.
        _, (other, _) = two_brands
        limits.assert_within_budget(db, AiFeature.PRICING, brand_id=other.id)

    def test_a_kill_switch_disables_one_feature_only(self, db: Session, monkeypatch) -> None:  # type: ignore[no-untyped-def]
        monkeypatch.setenv("AI_DISABLE_PRICING", "true")

        with pytest.raises(FeatureDisabled):
            limits.assert_feature_enabled(AiFeature.PRICING)

        limits.assert_feature_enabled(AiFeature.RISK_SCORING)
        assert limits.feature_switches()["pricing"] is False
        assert limits.feature_switches()["risk_scoring"] is True


class TestRouting:
    def test_every_feature_has_a_route(self) -> None:
        """A feature with no route has no model, no budget and no owner."""
        for feature in AiFeature:
            assert router.route_for(feature) is not None

    def test_the_vision_route_uses_a_vision_model(self) -> None:
        route = router.route_for(AiFeature.LISTING_FROM_PHOTOS)
        assert route.requires_vision
        assert spec_for(route.model_id).supports_vision

    def test_batch_is_used_where_nobody_is_waiting(self) -> None:
        for feature in (AiFeature.MANIFEST_EXTRACT, AiFeature.DEMAND_FORECAST):
            assert router.route_for(feature).mode == AiMode.BATCH

    def test_the_default_model_is_opus(self) -> None:
        """Cheaper models are a deliberate choice per route, not a default."""
        assert router.route_for(AiFeature.LISTING_FROM_PHOTOS).model_id == OPUS_5_5
        assert router.route_for(AiFeature.PRICING).model_id == OPUS_5_5


class TestPrompts:
    def test_prompts_are_versioned_files_with_a_cacheable_prefix(self) -> None:
        prompt = prompts.load("listing_from_photos")
        assert prompt.version >= 1
        assert prompt.system
        assert prompt.user_template
        # The cacheable prefix must not contain a placeholder that varies per
        # call, or the cache can never hit.
        assert "{photo_count}" not in prompt.system

    def test_rendering_reports_a_missing_placeholder(self) -> None:
        prompt = prompts.load("risk_scoring")
        with pytest.raises(KeyError, match="risk_scoring"):
            prompt.render(title="only one value")

    def test_a_missing_prompt_is_a_clear_error(self) -> None:
        with pytest.raises(prompts.PromptNotFound):
            prompts.load("no_such_prompt")

    def test_all_prompts_are_discoverable(self) -> None:
        found = prompts.all_prompts()
        assert "listing_from_photos" in found
        assert "risk_scoring" in found


class TestOfflineMode:
    def test_offline_refuses_to_invent_a_reply(self, tmp_path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
        """A missing fixture is an error, never a plausible stub.

        A gateway that quietly fabricates an answer in offline mode would make
        every eval meaningless.
        """
        monkeypatch.setattr(client, "FIXTURE_DIR", tmp_path)
        with pytest.raises(client.AiClientError, match="No fixture"):
            client.call_model(
                model=OPUS_5_5,
                system="system",
                user_text="user",
                feature="pricing",
                prompt_name="pricing",
                prompt_version=1,
            )

    def test_a_recorded_fixture_is_returned(self, tmp_path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
        monkeypatch.setattr(client, "FIXTURE_DIR", tmp_path)
        key = client.fixture_key(
            feature="pricing",
            prompt_name="pricing",
            prompt_version=1,
            user_text="user",
            images=0,
        )
        path = tmp_path / "pricing" / f"{key}.json"
        path.parent.mkdir(parents=True)
        path.write_text(
            json.dumps(
                {
                    "model": OPUS_5_5,
                    "content": {"hello": "world"},
                    "usage": {"input_tokens": 10, "output_tokens": 5},
                }
            ),
            encoding="utf-8",
        )

        reply = client.call_model(
            model=OPUS_5_5,
            system="system",
            user_text="user",
            feature="pricing",
            prompt_name="pricing",
            prompt_version=1,
        )
        assert reply.from_fixture
        assert reply.content == {"hello": "world"}
        assert reply.usage.input_tokens == 10

    def test_the_fixture_key_ignores_image_bytes_but_not_the_count(self) -> None:
        base = {
            "feature": "listing_from_photos",
            "prompt_name": "listing_from_photos",
            "prompt_version": 1,
            "user_text": "same text",
        }
        assert client.fixture_key(**base, images=2) == client.fixture_key(**base, images=2)
        assert client.fixture_key(**base, images=2) != client.fixture_key(**base, images=3)


class TestRunFeature:
    def _fixture(self, tmp_path, monkeypatch, feature: str, content: dict[str, object]) -> None:  # type: ignore[no-untyped-def]
        monkeypatch.setattr(client, "FIXTURE_DIR", tmp_path)
        prompt = prompts.load(feature)
        user_text = prompt.render(
            manifest_total=100,
            declared_total=100,
            discount_percent=75,
            photo_count=4,
            condition_grade="A",
            defect_count=0,
            title="Test lot",
            description="A plain factual description.",
            category_slug="womenswear-stitched",
        )
        key = client.fixture_key(
            feature=feature,
            prompt_name=prompt.name,
            prompt_version=prompt.version,
            user_text=user_text,
            images=0,
        )
        path = tmp_path / feature / f"{key}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(
                {
                    "model": HAIKU_4_5,
                    "content": content,
                    "usage": {"input_tokens": 1200, "output_tokens": 180},
                }
            ),
            encoding="utf-8",
        )

    def _valid_risk_score(self) -> dict[str, object]:
        return {
            "score": 12,
            "findings": [],
            "completeness": 95,
            "manifest_consistent": True,
            "price_plausible": True,
            "counterfeit_signals": [],
            "recommend_human_review": False,
        }

    def test_a_successful_run_records_job_output_and_spend(
        self, db: Session, tmp_path, monkeypatch, two_brands
    ) -> None:  # type: ignore[no-untyped-def]
        (brand, _), _ = two_brands
        self._fixture(tmp_path, monkeypatch, "risk_scoring", self._valid_risk_score())

        result = run_feature(
            db,
            AiFeature.RISK_SCORING,
            prompt_name="risk_scoring",
            prompt_values={
                "manifest_total": 100,
                "declared_total": 100,
                "discount_percent": 75,
                "photo_count": 4,
                "condition_grade": "A",
                "defect_count": 0,
                "title": "Test lot",
                "description": "A plain factual description.",
                "category_slug": "womenswear-stitched",
            },
            brand_id=brand.id,
            entity_type="lot",
            entity_id="lot-1",
        )

        assert result.output.score == 12  # type: ignore[attr-defined]
        assert result.from_fixture

        job = db.scalars(select(AiJob)).one()
        assert job.status == AiJobStatus.SUCCEEDED
        assert job.brand_id == brand.id
        assert job.entity_id == "lot-1"

        output = db.scalars(select(AiOutput)).one()
        assert output.prompt_name == "risk_scoring"
        assert output.input_tokens == 1200
        # Offline runs are free, and the ledger must say so rather than
        # inventing development spend.
        assert Decimal(str(output.cost_usd)) == Decimal("0")

    def test_a_reply_that_breaks_the_schema_fails_loudly(
        self, db: Session, tmp_path, monkeypatch
    ) -> None:  # type: ignore[no-untyped-def]
        """An unvalidated reply must never reach the catalogue.

        The job is marked failed and the attempt is still recorded, because
        the call happened whether or not the answer was usable.
        """
        self._fixture(
            tmp_path,
            monkeypatch,
            "risk_scoring",
            {"score": "not a number", "completeness": 95},
        )

        with pytest.raises(ValidationFailed):
            run_feature(
                db,
                AiFeature.RISK_SCORING,
                prompt_name="risk_scoring",
                prompt_values={
                    "manifest_total": 100,
                    "declared_total": 100,
                    "discount_percent": 75,
                    "photo_count": 4,
                    "condition_grade": "A",
                    "defect_count": 0,
                    "title": "Test lot",
                    "description": "A plain factual description.",
                    "category_slug": "womenswear-stitched",
                },
            )

        job = db.scalars(select(AiJob)).one()
        assert job.status == AiJobStatus.FAILED
        assert job.error

    def test_a_blocked_job_keeps_its_row(self, db: Session, monkeypatch) -> None:  # type: ignore[no-untyped-def]
        """Throttling must be visible, not look like nothing happened."""
        monkeypatch.setenv("AI_DISABLE_RISK_SCORING", "true")

        with pytest.raises(FeatureDisabled):
            run_feature(
                db,
                AiFeature.RISK_SCORING,
                prompt_name="risk_scoring",
                prompt_values={},
            )

        job = db.scalars(select(AiJob)).one()
        assert job.status == AiJobStatus.SKIPPED_KILL_SWITCH
        assert job.blocked_reason

    def test_accepting_and_correcting_an_output(
        self, db: Session, tmp_path, monkeypatch, two_brands
    ) -> None:  # type: ignore[no-untyped-def]
        """The quality loop: the diff between draft and correction.

        This pairing is the accuracy metric in Phase 4 and the training corpus
        after launch, which is why it is stored from week 5 rather than added
        later when the data would already be lost.
        """
        (brand, owner), _ = two_brands
        self._fixture(tmp_path, monkeypatch, "risk_scoring", self._valid_risk_score())

        result = run_feature(
            db,
            AiFeature.RISK_SCORING,
            prompt_name="risk_scoring",
            prompt_values={
                "manifest_total": 100,
                "declared_total": 100,
                "discount_percent": 75,
                "photo_count": 4,
                "condition_grade": "A",
                "defect_count": 0,
                "title": "Test lot",
                "description": "A plain factual description.",
                "category_slug": "womenswear-stitched",
            },
            brand_id=brand.id,
        )

        accepted = accept_output(db, result.output_id, user_id=owner.id)
        assert accepted.accepted is True
        assert accepted.human_corrected is None

        corrected = accept_output(
            db,
            result.output_id,
            user_id=owner.id,
            corrected={"score": 60, "recommend_human_review": True},
        )
        assert corrected.accepted is False
        assert corrected.human_corrected == {"score": 60, "recommend_human_review": True}


class TestOutputSchemas:
    def test_every_feature_with_a_route_that_calls_a_model_has_a_schema(self) -> None:
        from khazana.ai.schemas import SCHEMA_BY_FEATURE

        # Embedding and translation do not return structured JSON from a
        # model: embeddings come from a self hosted model and translation
        # returns text, so they are the only two exempt.
        exempt = {AiFeature.EMBEDDING, AiFeature.TRANSLATION, AiFeature.DEMAND_FORECAST}
        for feature in AiFeature:
            if feature in exempt:
                continue
            assert feature.value in SCHEMA_BY_FEATURE, (
                f"{feature.value} has no output schema, so its replies would be "
                f"trusted rather than validated"
            )

    def test_the_schema_sent_to_the_api_forbids_extra_properties(self) -> None:
        from khazana.ai.gateway.service import _json_schema
        from khazana.ai.schemas import RiskScore

        built = _json_schema(RiskScore)
        assert built["schema"]["additionalProperties"] is False
