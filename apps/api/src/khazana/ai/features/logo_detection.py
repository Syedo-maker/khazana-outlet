"""Find brand marks in a photograph bound for an unbranded listing.

The model suggests where marks are. Code pads those regions and applies the
blur, and the brand reviews the result before a buyer can see it. A reply that
says a person should look, or one that would hide too much of the photograph,
is sent to that review rather than treated as finished.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy.orm import Session

from ...models.enums import AiFeature, PhotoKind
from ..gateway import AiResult, run_feature
from ..logo_regions import Box, clip, pad, union_area
from ..schemas import LogoDetection

PROMPT = "logo_detection"

# Beyond this share of the image the blur is destroying the listing, so a
# person decides rather than the photograph being published that way.
MAX_AUTOMATIC_BLUR = 0.5
MAX_BRAND_NAME_CHARS = 160


@dataclass(slots=True)
class DetectionOutcome:
    detection: LogoDetection
    result: AiResult
    blur_boxes: list[Box]
    needs_review: bool
    review_reasons: list[str] = field(default_factory=list)


def detect(
    db: Session,
    *,
    image: bytes,
    photo_kind: PhotoKind,
    brand_name: str,
    brand_id: str,
    user_id: str | None = None,
    photo_id: str | None = None,
    record_fixture: bool = False,
) -> DetectionOutcome:
    result = run_feature(
        db,
        AiFeature.LOGO_DETECTION,
        prompt_name=PROMPT,
        prompt_values={
            "photo_kind": photo_kind.value,
            "brand_name": " ".join(brand_name.split())[:MAX_BRAND_NAME_CHARS],
        },
        images=[image],
        brand_id=brand_id,
        user_id=user_id,
        entity_type="lot_photo",
        entity_id=photo_id,
        record_fixture=record_fixture,
    )
    detection = result.output
    assert isinstance(detection, LogoDetection)

    boxes = [
        pad(clip(Box(region.x, region.y, region.width, region.height)))
        for region in detection.regions
    ]

    reasons: list[str] = []
    if not detection.image_readable:
        reasons.append("The photograph could not be inspected.")
    if detection.needs_human_review:
        reasons.append(detection.review_reason or "The check asked for a person to look.")
    if union_area(boxes) > MAX_AUTOMATIC_BLUR:
        reasons.append("The blur would hide more than half of the photograph.")

    return DetectionOutcome(
        detection=detection,
        result=result,
        blur_boxes=boxes,
        needs_review=bool(reasons),
        review_reasons=reasons,
    )
