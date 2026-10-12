"""Listing quality and risk scoring.

Scores a draft listing for how much human attention it needs before going
live, and orders the admin review queue. It never approves or rejects
anything: the brand approves, an admin moderates, and this only decides what
they look at first.

The division of labour matters here. Anything that can be computed is
computed, and the model is asked only for judgement:

- **Computed, authoritative.** Manifest sum against the stated total, implied
  discount, photograph count, defect count, grade against defects. These are
  facts. If the model disagrees with one, the computation wins, because a
  model that says the manifest balances when it does not would let a bad lot
  through on its say so.
- **Judged by the model.** Counterfeit signals, description quality, whether
  the wording and the claimed grade hang together.

The final score is the higher of the two, so a clean sounding description can
never talk a structurally broken listing down the queue.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session

from ...core.errors import NotFound
from ...models import Category, Lot, LotDefect, LotPhoto, ManifestLine
from ...models.enums import AiFeature, ConditionGrade
from ..gateway import AiResult, run_feature
from ..schemas import RiskFinding, RiskScore

logger = logging.getLogger(__name__)

PROMPT = "risk_scoring"

# A wholesale surplus discount outside this band is almost always a typed
# price rather than a real offer.
PLAUSIBLE_DISCOUNT_LOW = 30
PLAUSIBLE_DISCOUNT_HIGH = 92

MIN_PHOTOS = 3
REVIEW_SCORE = 50


@dataclass(slots=True)
class RiskOutcome:
    score: RiskScore
    result: AiResult
    computed_findings: list[RiskFinding] = field(default_factory=list)
    model_score: int = 0
    computed_score: int = 0

    @property
    def needs_human_review(self) -> bool:
        return self.score.score >= REVIEW_SCORE or self.score.recommend_human_review

    @property
    def blocking_findings(self) -> list[RiskFinding]:
        """Findings serious enough that a person must look before it goes live."""
        return [finding for finding in self.score.findings if finding.severity >= 4]


@dataclass(frozen=True, slots=True)
class ListingFacts:
    """The measurable half of a risk score.

    A dataclass rather than a dict because every one of these is read as a
    number or a flag. A dict of object forced a cast at every use, which is
    the type system pointing at a missing type rather than being awkward.
    """

    manifest_total: int
    declared_total: int
    manifest_consistent: bool
    discount_percent: int
    photo_count: int
    defect_count: int
    condition_grade: str
    category: str
    has_description: bool

    def as_prompt_values(self, lot: Lot) -> dict[str, object]:
        return {
            "manifest_total": self.manifest_total,
            "declared_total": self.declared_total,
            "discount_percent": self.discount_percent,
            "photo_count": self.photo_count,
            "condition_grade": self.condition_grade,
            "defect_count": self.defect_count,
            "title": (lot.title or "")[:200],
            "description": (lot.description or "")[:1500],
            "category_slug": self.category,
        }


def compute_facts(db: Session, lot: Lot) -> ListingFacts:
    """The things that are measured rather than judged."""
    lines = db.scalars(select(ManifestLine).where(ManifestLine.lot_id == lot.id)).all()
    defects = db.scalars(select(LotDefect).where(LotDefect.lot_id == lot.id)).all()
    photos = db.scalars(select(LotPhoto).where(LotPhoto.lot_id == lot.id)).all()
    category = db.get(Category, lot.category_id)

    manifest_total = sum(line.pieces for line in lines)
    return ListingFacts(
        manifest_total=manifest_total,
        declared_total=lot.total_pieces,
        manifest_consistent=manifest_total == lot.total_pieces,
        discount_percent=round(lot.discount_percent),
        photo_count=len(photos),
        defect_count=len(defects),
        condition_grade=lot.condition_grade.value,
        category=category.name if category else "unknown",
        has_description=bool((lot.description or "").strip()),
    )


def computed_findings(facts: ListingFacts, lot: Lot) -> tuple[list[RiskFinding], int]:
    """Structural problems, found without asking a model.

    Returns the findings and a score. These are not opinions, so they are not
    negotiable by anything the model says afterwards.
    """
    findings: list[RiskFinding] = []
    score = 0

    if not facts.manifest_consistent:
        difference = facts.manifest_total - facts.declared_total
        findings.append(
            RiskFinding(
                kind="manifest_mismatch",
                detail=(
                    f"The manifest sums to {facts.manifest_total} pieces but the "
                    f"lot declares {facts.declared_total}, a difference of "
                    f"{difference:+d}."
                ),
                severity=5,
            )
        )
        score = max(score, 90)

    discount = facts.discount_percent
    if discount < PLAUSIBLE_DISCOUNT_LOW:
        findings.append(
            RiskFinding(
                kind="discount_implausibly_small",
                detail=(
                    f"Only {discount} percent off retail. Wholesale surplus is "
                    "rarely under 30 percent off, so this is usually a mistyped "
                    "retail price."
                ),
                severity=3,
            )
        )
        score = max(score, 55)
    elif discount > PLAUSIBLE_DISCOUNT_HIGH:
        findings.append(
            RiskFinding(
                kind="discount_implausibly_large",
                detail=(
                    f"{discount} percent off retail. This is usually a mistyped lot "
                    "price and would sell at a loss if it is wrong."
                ),
                severity=4,
            )
        )
        score = max(score, 70)

    photo_count = facts.photo_count
    if photo_count == 0:
        findings.append(
            RiskFinding(
                kind="no_photographs",
                detail="The lot has no photographs, so a buyer cannot assess it.",
                severity=5,
            )
        )
        score = max(score, 85)
    elif photo_count < MIN_PHOTOS:
        findings.append(
            RiskFinding(
                kind="too_few_photographs",
                detail=(
                    f"Only {photo_count} photographs. Buyers need at least "
                    f"{MIN_PHOTOS}: the full lot, a single piece, and the label."
                ),
                severity=2,
            )
        )
        score = max(score, 35)

    # Grade C exists precisely to carry defects. Claiming it without listing
    # any means the buyer cannot see what they are accepting.
    if lot.condition_grade == ConditionGrade.C and facts.defect_count == 0:
        findings.append(
            RiskFinding(
                kind="grade_c_without_defects",
                detail=(
                    "Graded C but no defects are itemised, so a buyer cannot see "
                    "what they are accepting."
                ),
                severity=4,
            )
        )
        score = max(score, 65)

    # The reverse: defects listed on a lot claiming to be new with tags.
    if lot.condition_grade == ConditionGrade.A and facts.defect_count > 0:
        findings.append(
            RiskFinding(
                kind="grade_a_with_defects",
                detail=(
                    f"Graded A, meaning new with no defects, but "
                    f"{facts.defect_count} defects are listed."
                ),
                severity=4,
            )
        )
        score = max(score, 70)

    if not facts.has_description:
        findings.append(
            RiskFinding(
                kind="no_description",
                detail="The lot has no description.",
                severity=2,
            )
        )
        score = max(score, 30)

    return findings, score


def score_lot(
    db: Session,
    lot_id: str,
    *,
    user_id: str | None = None,
    record_fixture: bool = False,
) -> RiskOutcome:
    """Score one lot and return the combined result."""
    lot = db.get(Lot, lot_id)
    if lot is None or lot.is_deleted:
        raise NotFound("That lot does not exist.")

    facts = compute_facts(db, lot)
    structural, structural_score = computed_findings(facts, lot)

    result = run_feature(
        db,
        AiFeature.RISK_SCORING,
        prompt_name=PROMPT,
        prompt_values=facts.as_prompt_values(lot),
        brand_id=lot.brand_id,
        user_id=user_id,
        entity_type="lot",
        entity_id=lot.id,
        record_fixture=record_fixture,
    )

    judged = result.output
    assert isinstance(judged, RiskScore)

    combined = combine(judged, structural, structural_score, facts)

    return RiskOutcome(
        score=combined,
        result=result,
        computed_findings=structural,
        model_score=judged.score,
        computed_score=structural_score,
    )


def combine(
    judged: RiskScore,
    structural: list[RiskFinding],
    structural_score: int,
    facts: ListingFacts,
) -> RiskScore:
    """Merge the measured findings with the judged ones.

    Two rules, both one directional on purpose.

    The score is the higher of the two, so a well written description cannot
    talk a structurally broken listing down the queue.

    ``manifest_consistent`` is taken from the computation, never from the
    model. A model asserting that a manifest balances when it does not is the
    one error that would let a bad lot through on its say so.
    """
    measured_consistency = facts.manifest_consistent
    if judged.manifest_consistent != measured_consistency:
        logger.warning(
            "risk model said manifest_consistent=%s, measurement says %s, keeping the measurement",
            judged.manifest_consistent,
            measured_consistency,
        )

    # Structural findings first: an admin reads top down.
    merged = [*structural, *judged.findings]
    score = max(judged.score, structural_score)

    return judged.model_copy(
        update={
            "score": score,
            "findings": merged[:12],
            "manifest_consistent": measured_consistency,
            "recommend_human_review": (
                judged.recommend_human_review
                or score >= REVIEW_SCORE
                or any(finding.severity >= 4 for finding in merged)
            ),
        }
    )


def queue_order(outcomes: list[RiskOutcome]) -> list[RiskOutcome]:
    """Order the admin review queue, most concerning first.

    Sorting is here rather than in the database because the score is produced
    per listing at submission time and the queue is short. When the queue
    stops being short, this becomes an indexed column.
    """
    return sorted(
        outcomes,
        key=lambda outcome: (
            -outcome.score.score,
            -len(outcome.blocking_findings),
        ),
    )
