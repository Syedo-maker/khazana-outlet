"""Photo to listing, and the image preparation that keeps it affordable.

These tests cover the three guards that sit between the model and the
catalogue, because the model being good is not the same as the output being
safe to apply:

- an invented category never reaches the catalogue,
- a condition grade is never talked up,
- a low confidence draft is routed to a person.
"""

from __future__ import annotations

import io
import json

import pytest
from sqlalchemy.orm import Session

from khazana.ai.features import listing_from_photos as feature
from khazana.ai.gateway import client, prompts
from khazana.ai.images import (
    MAX_EDGE_PX,
    MAX_IMAGES_PER_CALL,
    ImageError,
    prepare,
    prepare_batch,
    select_for_call,
)
from khazana.core.errors import ValidationFailed
from khazana.models import Category
from khazana.models.enums import ConditionGrade, PhotoKind


def make_image(width: int, height: int, fmt: str = "JPEG") -> bytes:
    from PIL import Image

    image = Image.new("RGB", (width, height), (120, 90, 60))
    buffer = io.BytesIO()
    image.save(buffer, format=fmt)
    return buffer.getvalue()


# ----------------------------------------------------------------- images


class TestImagePreparation:
    def test_a_large_photo_is_shrunk_to_the_cap(self) -> None:
        prepared = prepare(make_image(4000, 3000))
        assert max(prepared.width, prepared.height) == MAX_EDGE_PX
        assert prepared.height == 768

    def test_a_small_photo_is_left_at_its_size(self) -> None:
        prepared = prepare(make_image(640, 480))
        assert (prepared.width, prepared.height) == (640, 480)

    def test_compression_actually_saves_bytes(self) -> None:
        """The whole point of this module.

        Image tokens dominate the cost of the listing call, so a preparation
        step that does not shrink anything is a preparation step that is
        quietly broken.
        """
        prepared = prepare(make_image(3000, 3000, fmt="PNG"))
        assert prepared.saved_bytes > 0
        assert prepared.saved_percent > 50

    def test_a_png_with_transparency_is_converted(self) -> None:
        """Brands upload PNGs with alpha and CMYK scans. Both break JPEG."""
        from PIL import Image

        image = Image.new("RGBA", (800, 600), (10, 20, 30, 128))
        buffer = io.BytesIO()
        image.save(buffer, format="PNG")

        prepared = prepare(buffer.getvalue())
        assert prepared.data.startswith(b"\xff\xd8\xff")

    def test_a_non_image_is_refused_clearly(self) -> None:
        with pytest.raises(ImageError, match="JPEG or PNG"):
            prepare(b"this is not an image")

    def test_only_the_best_views_are_sent(self) -> None:
        photos = [
            (PhotoKind.PACKAGING, b"p"),
            (PhotoKind.FRONT, b"f"),
            (PhotoKind.LABEL, b"l"),
            (PhotoKind.BACK, b"b"),
            (PhotoKind.FULL_LOT, b"w"),
            (PhotoKind.SIZE_SPREAD, b"s"),
        ]
        chosen = select_for_call(photos)

        assert len(chosen) == MAX_IMAGES_PER_CALL
        assert [kind for kind, _ in chosen] == [
            PhotoKind.FRONT,
            PhotoKind.LABEL,
            PhotoKind.FULL_LOT,
            PhotoKind.BACK,
        ]

    def test_duplicate_views_are_collapsed(self) -> None:
        """Two front shots are one view, and sending both doubles the cost."""
        photos = [(PhotoKind.FRONT, b"a"), (PhotoKind.FRONT, b"b"), (PhotoKind.LABEL, b"c")]
        chosen = select_for_call(photos)
        assert len(chosen) == 2

    def test_batch_reports_what_it_saved(self) -> None:
        photos = [(PhotoKind.FRONT, make_image(2500, 2500, fmt="PNG"))]
        images, stats = prepare_batch(photos)

        assert len(images) == 1
        assert stats["photos_sent"] == 1
        assert stats["bytes_saved"] > 0
        assert stats["bytes_after"] < stats["bytes_before"]


# ---------------------------------------------------------------- feature


@pytest.fixture
def taxonomy(db: Session) -> list[Category]:
    parent = Category(name="Apparel", slug="apparel")
    db.add(parent)
    db.flush()
    rows = [
        Category(name="Womenswear stitched", slug="womenswear-stitched", parent_id=parent.id),
        Category(name="Menswear", slug="menswear", parent_id=parent.id),
    ]
    db.add_all(rows)
    db.commit()
    return rows


def good_draft(**overrides: object) -> dict[str, object]:
    base: dict[str, object] = {
        "title": "Stitched lawn suits, summer surplus",
        "description": "Printed cotton lawn suits. Tags attached on the pieces shown.",
        "category_slug": "womenswear-stitched",
        "colors": ["beige", "maroon"],
        "material": "cotton lawn",
        "apparent_condition": "A",
        "suggested_sizes": ["M", "L"],
        "tags": ["lawn", "stitched"],
        "confidence": 0.85,
        "uncertain_fields": [],
    }
    base.update(overrides)
    return base


def stub_reply(tmp_path, monkeypatch, db: Session, content: dict[str, object], images: int) -> None:  # type: ignore[no-untyped-def]
    """Record a fixture for exactly the call the feature is about to make."""
    monkeypatch.setattr(client, "FIXTURE_DIR", tmp_path)
    prompt = prompts.load(feature.PROMPT)
    user_text = prompt.render(
        category_list=feature.taxonomy_for_prompt(db),
        brand_title="",
        brand_notes="",
        season="",
        photo_count=images,
    )
    key = client.fixture_key(
        feature="listing_from_photos",
        prompt_name=prompt.name,
        prompt_version=prompt.version,
        user_text=user_text,
        images=images,
    )
    path = tmp_path / "listing_from_photos" / f"{key}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "model": "claude-opus-5-5",
                "content": content,
                "usage": {"input_tokens": 7400, "output_tokens": 420, "cache_read_tokens": 1800},
            }
        ),
        encoding="utf-8",
    )


class TestDraftFromPhotos:
    def test_a_clean_draft_comes_back_ready(
        self, db: Session, two_brands, taxonomy, tmp_path, monkeypatch
    ) -> None:  # type: ignore[no-untyped-def]
        (brand, _), _ = two_brands
        stub_reply(tmp_path, monkeypatch, db, good_draft(), images=1)

        outcome = feature.draft_from_photos(
            db,
            photos=[(PhotoKind.FRONT, make_image(1200, 1200))],
            brand_id=brand.id,
        )

        assert outcome.draft.category_slug == "womenswear-stitched"
        assert outcome.draft.confidence == 0.85
        assert not outcome.needs_review
        assert outcome.image_stats["photos_sent"] == 1

    def test_an_invented_category_never_reaches_the_catalogue(
        self, db: Session, two_brands, taxonomy, tmp_path, monkeypatch
    ) -> None:  # type: ignore[no-untyped-def]
        """The prompt says choose from the list. This proves it anyway.

        A prompt instruction is guidance, not a guarantee, and a catalogue
        full of invented category slugs is very hard to clean up later.
        """
        (brand, _), _ = two_brands
        stub_reply(tmp_path, monkeypatch, db, good_draft(category_slug="luxury-handbags"), images=1)

        outcome = feature.draft_from_photos(
            db,
            photos=[(PhotoKind.FRONT, make_image(800, 800))],
            brand_id=brand.id,
        )

        assert outcome.draft.category_slug == "other"
        assert outcome.needs_review
        assert any("does not exist" in reason for reason in outcome.review_reasons)

    def test_a_grade_is_never_talked_up(
        self, db: Session, two_brands, taxonomy, tmp_path, monkeypatch
    ) -> None:  # type: ignore[no-untyped-def]
        """A lot sold as B that arrives as C loses that buyer permanently.

        So the model may grade down, never up, and the stricter of the two
        always wins.
        """
        (brand, _), _ = two_brands
        stub_reply(tmp_path, monkeypatch, db, good_draft(apparent_condition="A"), images=1)

        outcome = feature.draft_from_photos(
            db,
            photos=[(PhotoKind.FRONT, make_image(800, 800))],
            brand_id=brand.id,
            claimed_grade=ConditionGrade.C,
        )

        assert outcome.draft.apparent_condition == ConditionGrade.C
        assert outcome.needs_review

    def test_a_worse_grade_is_kept_and_flagged(
        self, db: Session, two_brands, taxonomy, tmp_path, monkeypatch
    ) -> None:  # type: ignore[no-untyped-def]
        (brand, _), _ = two_brands
        stub_reply(tmp_path, monkeypatch, db, good_draft(apparent_condition="C"), images=1)

        outcome = feature.draft_from_photos(
            db,
            photos=[(PhotoKind.FRONT, make_image(800, 800))],
            brand_id=brand.id,
            claimed_grade=ConditionGrade.A,
        )

        assert outcome.draft.apparent_condition == ConditionGrade.C
        assert any("worse than" in reason for reason in outcome.review_reasons)

    def test_low_confidence_routes_to_a_person(
        self, db: Session, two_brands, taxonomy, tmp_path, monkeypatch
    ) -> None:  # type: ignore[no-untyped-def]
        (brand, _), _ = two_brands
        stub_reply(
            tmp_path,
            monkeypatch,
            db,
            good_draft(confidence=0.3, uncertain_fields=["material", "colour range"]),
            images=1,
        )

        outcome = feature.draft_from_photos(
            db,
            photos=[(PhotoKind.FRONT, make_image(800, 800))],
            brand_id=brand.id,
        )

        assert outcome.needs_review
        assert any("Confidence was 30%" in reason for reason in outcome.review_reasons)

    def test_no_photographs_is_refused_before_any_cost(
        self, db: Session, two_brands, taxonomy
    ) -> None:  # type: ignore[no-untyped-def]
        (brand, _), _ = two_brands
        with pytest.raises(ValidationFailed, match="at least one photograph"):
            feature.draft_from_photos(db, photos=[], brand_id=brand.id)

    def test_an_empty_taxonomy_is_a_clear_error(self, db: Session, two_brands) -> None:  # type: ignore[no-untyped-def]
        (brand, _), _ = two_brands
        with pytest.raises(ValidationFailed, match="No categories exist"):
            feature.draft_from_photos(
                db,
                photos=[(PhotoKind.FRONT, make_image(400, 400))],
                brand_id=brand.id,
            )

    def test_untrusted_brand_text_is_bounded(self) -> None:
        """A pasted novel in the notes field must not become 40,000 tokens."""
        assert len(feature._clip("x" * 9_000)) == 500
        assert feature._clip("  spaced   out  text ") == "spaced out text"
        assert feature._clip(None) == ""


class TestTaxonomy:
    def test_only_leaf_categories_are_offered(self, db: Session, taxonomy) -> None:  # type: ignore[no-untyped-def]
        """A model should not be able to file a lot under a parent heading."""
        listed = feature.taxonomy_for_prompt(db)
        assert "womenswear-stitched" in listed
        assert "menswear" in listed
        assert "- apparel:" not in listed
        assert "- other:" in listed
