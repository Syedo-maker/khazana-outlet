"""Listing risk scoring.

The property under test is the division of labour: anything measurable is
measured and is not negotiable by the model, and the model's judgement can
only ever raise concern, never lower it.
"""

from __future__ import annotations

import json

import pytest
from sqlalchemy.orm import Session

from khazana.ai.features import risk_scoring as feature
from khazana.ai.gateway import client, prompts
from khazana.ai.schemas import RiskFinding, RiskScore
from khazana.core.errors import NotFound
from khazana.models import Category, Lot, LotDefect, LotPhoto, ManifestLine
from khazana.models.enums import ConditionGrade, LotStatus, PhotoKind, Visibility


@pytest.fixture
def category(db: Session) -> Category:
    row = Category(name="Womenswear stitched", slug="womenswear-stitched")
    db.add(row)
    db.commit()
    return row


def make_lot(
    db: Session,
    brand_id: str,
    category_id: str,
    *,
    code: str = "LOT-R1",
    pieces: int = 100,
    manifest_pieces: int | None = None,
    retail: int = 2_000,
    lot_price: int = 50_000,
    grade: ConditionGrade = ConditionGrade.A,
    photos: int = 4,
    defects: int = 0,
    description: str | None = "Printed lawn suits, summer surplus.",
) -> Lot:
    lot = Lot(
        lot_code=code,
        brand_id=brand_id,
        category_id=category_id,
        title="Printed lawn suits",
        description=description,
        condition_grade=grade,
        total_pieces=pieces,
        retail_price_per_piece_pkr=retail,
        lot_price_pkr=lot_price,
        min_order_pieces=pieces,
        stock_city="Lahore",
        status=LotStatus.DRAFT,
        visibility=Visibility.PRIVATE,
    )
    db.add(lot)
    db.flush()

    db.add(
        ManifestLine(
            lot_id=lot.id,
            brand_id=brand_id,
            size="M",
            color="black",
            pieces=manifest_pieces if manifest_pieces is not None else pieces,
        )
    )
    for index in range(photos):
        db.add(
            LotPhoto(
                lot_id=lot.id,
                brand_id=brand_id,
                file_key=f"seed/{code}/{index}.jpg",
                kind=PhotoKind.FRONT,
                sort_order=index,
            )
        )
    for index in range(defects):
        db.add(
            LotDefect(
                lot_id=lot.id,
                brand_id=brand_id,
                issue=f"mark {index}",
                pieces_affected=1,
            )
        )
    db.commit()
    return lot


def clean_model_score(**overrides: object) -> dict[str, object]:
    base: dict[str, object] = {
        "score": 10,
        "findings": [],
        "completeness": 95,
        "manifest_consistent": True,
        "price_plausible": True,
        "counterfeit_signals": [],
        "recommend_human_review": False,
    }
    base.update(overrides)
    return base


def stub(db: Session, lot: Lot, tmp_path, monkeypatch, content: dict) -> None:
    monkeypatch.setattr(client, "FIXTURE_DIR", tmp_path)
    facts = feature.compute_facts(db, lot)
    prompt = prompts.load(feature.PROMPT)
    user_text = prompt.render(
        manifest_total=facts["manifest_total"],
        declared_total=facts["declared_total"],
        discount_percent=facts["discount_percent"],
        photo_count=facts["photo_count"],
        condition_grade=facts["condition_grade"],
        defect_count=facts["defect_count"],
        title=(lot.title or "")[:200],
        description=(lot.description or "")[:1500],
        category_slug=facts["category"],
    )
    key = client.fixture_key(
        feature="risk_scoring",
        prompt_name=prompt.name,
        prompt_version=prompt.version,
        user_text=user_text,
        images=0,
    )
    path = tmp_path / "risk_scoring" / f"{key}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "model": "claude-haiku-4-5",
                "content": content,
                "usage": {"input_tokens": 900, "output_tokens": 180},
            }
        ),
        encoding="utf-8",
    )


class TestComputedFindings:
    def test_a_manifest_mismatch_is_the_most_severe_finding(
        self, db: Session, two_brands, category
    ) -> None:
        (brand, _), _ = two_brands
        lot = make_lot(db, brand.id, category.id, pieces=100, manifest_pieces=40)

        facts = feature.compute_facts(db, lot)
        findings, score = feature.computed_findings(facts, lot)

        assert facts["manifest_consistent"] is False
        kinds = {finding.kind for finding in findings}
        assert "manifest_mismatch" in kinds
        assert score >= 90
        assert any(finding.severity == 5 for finding in findings)

    def test_an_implausibly_large_discount_is_flagged(
        self, db: Session, two_brands, category
    ) -> None:
        """Almost always a mistyped price, and it would sell at a loss."""
        (brand, _), _ = two_brands
        lot = make_lot(db, brand.id, category.id, retail=2_000, lot_price=5_000, pieces=100)

        facts = feature.compute_facts(db, lot)
        findings, score = feature.computed_findings(facts, lot)

        assert facts["discount_percent"] == 98
        assert "discount_implausibly_large" in {finding.kind for finding in findings}
        assert score >= 70

    def test_an_implausibly_small_discount_is_flagged(
        self, db: Session, two_brands, category
    ) -> None:
        (brand, _), _ = two_brands
        lot = make_lot(db, brand.id, category.id, retail=2_000, lot_price=190_000, pieces=100)

        findings, _score = feature.computed_findings(feature.compute_facts(db, lot), lot)
        assert "discount_implausibly_small" in {finding.kind for finding in findings}

    def test_no_photographs_is_severe(self, db: Session, two_brands, category) -> None:
        (brand, _), _ = two_brands
        lot = make_lot(db, brand.id, category.id, photos=0)

        findings, score = feature.computed_findings(feature.compute_facts(db, lot), lot)

        assert "no_photographs" in {finding.kind for finding in findings}
        assert score >= 85

    def test_grade_c_without_itemised_defects_is_flagged(
        self, db: Session, two_brands, category
    ) -> None:
        """Grade C exists to carry defects, so claiming it with none hides them."""
        (brand, _), _ = two_brands
        lot = make_lot(db, brand.id, category.id, grade=ConditionGrade.C, defects=0)

        findings, _score = feature.computed_findings(feature.compute_facts(db, lot), lot)
        assert "grade_c_without_defects" in {finding.kind for finding in findings}

    def test_grade_a_with_defects_is_flagged(self, db: Session, two_brands, category) -> None:
        (brand, _), _ = two_brands
        lot = make_lot(db, brand.id, category.id, grade=ConditionGrade.A, defects=2)

        findings, _score = feature.computed_findings(feature.compute_facts(db, lot), lot)
        assert "grade_a_with_defects" in {finding.kind for finding in findings}

    def test_a_clean_lot_produces_nothing(self, db: Session, two_brands, category) -> None:
        """A clean listing must score zero, or the signal is worthless."""
        (brand, _), _ = two_brands
        lot = make_lot(db, brand.id, category.id)

        findings, score = feature.computed_findings(feature.compute_facts(db, lot), lot)

        assert findings == []
        assert score == 0


class TestCombine:
    def _facts(self, consistent: bool) -> dict[str, object]:
        return {"manifest_consistent": consistent, "manifest_total": 100, "declared_total": 100}

    def test_the_measurement_beats_the_model_on_the_manifest(self) -> None:
        """The one error that would let a bad lot through on the model's say so."""
        judged = RiskScore(**clean_model_score(manifest_consistent=True))  # type: ignore[arg-type]

        combined = feature.combine(judged, [], 90, self._facts(consistent=False))

        assert combined.manifest_consistent is False

    def test_the_higher_score_wins(self) -> None:
        """A well written description cannot talk a broken listing down the queue."""
        judged = RiskScore(**clean_model_score(score=5))  # type: ignore[arg-type]

        combined = feature.combine(judged, [], 90, self._facts(consistent=True))

        assert combined.score == 90

    def test_the_model_can_raise_the_score_on_its_own(self) -> None:
        judged = RiskScore(
            **clean_model_score(
                score=75,
                counterfeit_signals=["brand spelling differs between title and label"],
            )  # type: ignore[arg-type]
        )

        combined = feature.combine(judged, [], 0, self._facts(consistent=True))

        assert combined.score == 75
        assert combined.recommend_human_review is True

    def test_structural_findings_are_listed_first(self) -> None:
        """An admin reads the queue top down."""
        judged = RiskScore(
            **clean_model_score(
                findings=[{"kind": "wording", "detail": "vague description", "severity": 1}]
            )  # type: ignore[arg-type]
        )
        structural = [
            RiskFinding(kind="manifest_mismatch", detail="does not sum", severity=5)
        ]

        combined = feature.combine(judged, structural, 90, self._facts(consistent=False))

        assert combined.findings[0].kind == "manifest_mismatch"

    def test_a_severe_finding_forces_review_whatever_the_model_said(self) -> None:
        judged = RiskScore(**clean_model_score(recommend_human_review=False))  # type: ignore[arg-type]
        structural = [RiskFinding(kind="no_photographs", detail="none", severity=5)]

        combined = feature.combine(judged, structural, 85, self._facts(consistent=True))

        assert combined.recommend_human_review is True


class TestScoreLot:
    def test_a_clean_lot_scores_low_and_needs_no_review(
        self, db: Session, two_brands, category, tmp_path, monkeypatch
    ) -> None:
        (brand, _), _ = two_brands
        lot = make_lot(db, brand.id, category.id)
        stub(db, lot, tmp_path, monkeypatch, clean_model_score())

        outcome = feature.score_lot(db, lot.id)

        assert outcome.score.score == 10
        assert outcome.computed_findings == []
        assert not outcome.needs_human_review

    def test_a_broken_lot_is_escalated_despite_a_calm_model(
        self, db: Session, two_brands, category, tmp_path, monkeypatch
    ) -> None:
        """The headline case: the measurement overrides a reassuring model."""
        (brand, _), _ = two_brands
        lot = make_lot(db, brand.id, category.id, pieces=100, manifest_pieces=10, photos=0)
        stub(db, lot, tmp_path, monkeypatch, clean_model_score(score=5))

        outcome = feature.score_lot(db, lot.id)

        assert outcome.model_score == 5
        assert outcome.computed_score >= 90
        assert outcome.score.score >= 90
        assert outcome.needs_human_review
        assert outcome.score.manifest_consistent is False
        assert len(outcome.blocking_findings) >= 2

    def test_a_missing_lot_is_a_clear_error(self, db: Session) -> None:
        with pytest.raises(NotFound):
            feature.score_lot(db, "no-such-lot")


class TestQueueOrder:
    def test_the_queue_puts_the_worst_first(self) -> None:
        def outcome(score: int, severity: int) -> feature.RiskOutcome:
            return feature.RiskOutcome(
                score=RiskScore(
                    **clean_model_score(
                        score=score,
                        findings=[{"kind": "x", "detail": "y", "severity": severity}],
                    )  # type: ignore[arg-type]
                ),
                result=None,  # type: ignore[arg-type]
            )

        ordered = feature.queue_order([outcome(20, 1), outcome(90, 5), outcome(55, 3)])

        assert [item.score.score for item in ordered] == [90, 55, 20]
