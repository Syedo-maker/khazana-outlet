"""Photo to listing.

The highest value feature in the platform. A brand uploads photographs of a
lot and gets back a complete draft listing, which removes the work brands
dislike most: typing thirty fields per lot.

What this module does beyond calling the model:

- Prepares the photographs, because image tokens dominate the cost.
- Supplies the real category taxonomy from the database, so the model picks a
  slug that exists rather than inventing one.
- Validates the returned slug against that taxonomy anyway, because a prompt
  instruction is not a guarantee.
- Refuses to upgrade a condition grade. A model that says grade A is accepted
  only when the brand has not already said otherwise.
- Routes a low confidence draft to review instead of letting it be applied.

What it does not do: publish anything. The output is a draft, the brand
corrects it, and both versions are stored.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session

from ...core.errors import NotFound, ValidationFailed
from ...models import Category, Lot, LotPhoto
from ...models.enums import AiFeature, ConditionGrade, PhotoKind
from ..gateway import AiResult, run_feature
from ..images import prepare_batch
from ..schemas import ListingDraft

logger = logging.getLogger(__name__)

PROMPT = "listing_from_photos"

# Below this, a person checks the draft before it can be submitted. Poor
# photographs are common and an unchecked bad draft becomes a dispute later.
REVIEW_THRESHOLD = 0.6

# A model may grade a lot worse than the brand claimed, never better. The
# asymmetry is deliberate: a lot sold as B that arrives as C loses a buyer
# permanently, and the reverse costs nothing.
GRADE_ORDER = {ConditionGrade.A: 0, ConditionGrade.B: 1, ConditionGrade.C: 2}


@dataclass(slots=True)
class DraftOutcome:
    draft: ListingDraft
    result: AiResult
    needs_review: bool
    review_reasons: list[str] = field(default_factory=list)
    image_stats: dict[str, int] = field(default_factory=dict)

    @property
    def category_slug(self) -> str:
        return self.draft.category_slug


def taxonomy_for_prompt(db: Session) -> str:
    """The category list the model must choose from.

    Read from the database rather than hard coded in the prompt, so adding a
    category is a row and not a prompt edit. It sits in the cached prefix, so
    it costs almost nothing after the first call of the day.
    """
    rows = db.scalars(
        select(Category).where(Category.parent_id.is_not(None)).order_by(Category.slug)
    ).all()
    if not rows:
        raise ValidationFailed(
            "No categories exist yet. Run the seed or create the taxonomy before "
            "using the listing feature, because the model must choose from it."
        )
    lines = [f"- {row.slug}: {row.name}" for row in rows]
    lines.append("- other: nothing above fits")
    return "\n".join(lines)


def valid_slugs(db: Session) -> set[str]:
    return set(db.scalars(select(Category.slug)).all()) | {"other"}


def draft_from_photos(
    db: Session,
    *,
    photos: list[tuple[PhotoKind, bytes]],
    brand_id: str,
    user_id: str | None = None,
    lot_id: str | None = None,
    brand_title: str = "",
    brand_notes: str = "",
    season: str = "",
    claimed_grade: ConditionGrade | None = None,
    record_fixture: bool = False,
) -> DraftOutcome:
    """Produce a draft listing from photographs of one lot."""
    if not photos:
        raise ValidationFailed("Upload at least one photograph of the lot.")

    images, image_stats = prepare_batch(photos)

    result = run_feature(
        db,
        AiFeature.LISTING_FROM_PHOTOS,
        prompt_name=PROMPT,
        prompt_values={
            "category_list": taxonomy_for_prompt(db),
            # Brand supplied text is passed as context and labelled untrusted
            # in the prompt. It is never concatenated into the instructions.
            "brand_title": _clip(brand_title),
            "brand_notes": _clip(brand_notes),
            "season": _clip(season, 60),
            "photo_count": len(images),
        },
        images=images,
        brand_id=brand_id,
        user_id=user_id,
        entity_type="lot" if lot_id else "photo_set",
        entity_id=lot_id,
        record_fixture=record_fixture,
    )

    draft = result.output
    assert isinstance(draft, ListingDraft)

    reasons: list[str] = []

    # The model was told to choose from the taxonomy. Trust but verify: an
    # invented slug would break the catalogue, so it falls back to other.
    allowed = valid_slugs(db)
    if draft.category_slug not in allowed:
        logger.warning(
            "listing draft returned unknown category %r, falling back to other",
            draft.category_slug,
        )
        reasons.append(
            f"The suggested category {draft.category_slug!r} does not exist, "
            "so it has been set to other."
        )
        draft = draft.model_copy(update={"category_slug": "other"})

    # Never let the model talk a grade up.
    if claimed_grade is not None:
        if GRADE_ORDER[draft.apparent_condition] < GRADE_ORDER[claimed_grade]:
            reasons.append(
                f"The photographs looked like grade {draft.apparent_condition.value}, "
                f"but the lot is listed as {claimed_grade.value}. The stricter "
                "grade has been kept."
            )
            draft = draft.model_copy(update={"apparent_condition": claimed_grade})
        elif GRADE_ORDER[draft.apparent_condition] > GRADE_ORDER[claimed_grade]:
            reasons.append(
                f"The photographs suggest grade {draft.apparent_condition.value}, "
                f"which is worse than the {claimed_grade.value} claimed. Check "
                "before publishing."
            )

    if draft.confidence < REVIEW_THRESHOLD:
        reasons.append(
            f"Confidence was {draft.confidence:.0%}, below the {REVIEW_THRESHOLD:.0%} "
            "threshold. Usually this means the photographs are unclear."
        )

    if draft.uncertain_fields:
        reasons.append(
            "The model could not determine: " + ", ".join(draft.uncertain_fields[:6]) + "."
        )

    return DraftOutcome(
        draft=draft,
        result=result,
        needs_review=draft.confidence < REVIEW_THRESHOLD or bool(reasons),
        review_reasons=reasons,
        image_stats=image_stats,
    )


def draft_for_lot(
    db: Session,
    lot_id: str,
    *,
    user_id: str | None = None,
    load_photo: object = None,
    record_fixture: bool = False,
) -> DraftOutcome:
    """Draft a listing for a lot that already has photographs stored.

    ``load_photo`` is a callable taking a storage key and returning bytes. It
    is injected rather than imported so the storage backend stays swappable
    and the tests need no filesystem.
    """
    lot = db.get(Lot, lot_id)
    if lot is None or lot.is_deleted:
        raise NotFound("That lot does not exist.")

    rows = db.scalars(
        select(LotPhoto).where(LotPhoto.lot_id == lot_id).order_by(LotPhoto.sort_order)
    ).all()
    if not rows:
        raise ValidationFailed(
            "This lot has no photographs yet. Upload at least one before asking "
            "for a draft listing."
        )

    if load_photo is None:
        from ...storage import read_object

        load_photo = read_object

    photos: list[tuple[PhotoKind, bytes]] = []
    for row in rows:
        try:
            photos.append((row.kind, load_photo(row.file_key)))  # type: ignore[operator]
        except FileNotFoundError:
            logger.warning("photo %s missing from storage, skipping", row.file_key)

    if not photos:
        raise ValidationFailed("None of this lot's photographs could be read from storage.")

    return draft_from_photos(
        db,
        photos=photos,
        brand_id=lot.brand_id,
        user_id=user_id,
        lot_id=lot.id,
        brand_title=lot.title or "",
        brand_notes=lot.description or "",
        season=lot.season or "",
        claimed_grade=lot.condition_grade,
        record_fixture=record_fixture,
    )


def apply_draft(db: Session, lot: Lot, draft: ListingDraft, *, category_id: str) -> Lot:
    """Write an accepted draft onto the lot.

    Only the descriptive fields. Price, piece counts and the manifest are the
    brand's to state and are never touched by a model, which is the boundary
    in docs/ai-architecture.md section 2.
    """
    lot.title = draft.title[:200]
    lot.description = draft.description
    lot.category_id = category_id
    db.flush()
    return lot


def _clip(text: str | None, limit: int = 500) -> str:
    """Bound untrusted brand text before it enters a prompt.

    A 40,000 character description pasted into a notes field would otherwise
    become 40,000 input tokens on every retry.
    """
    if not text:
        return ""
    cleaned = " ".join(text.split())
    return cleaned[:limit]
