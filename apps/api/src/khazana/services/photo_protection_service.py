"""Keeping a brand's identity out of the photographs on an unbranded listing.

The rule this module exists to enforce: a buyer of an unbranded lot receives a
photograph only after the brand has reviewed what that buyer will see. Anything
not yet inspected, held for review or failed is withheld, so every error path
ends with a missing photograph rather than an exposed brand.

The model only proposes regions. The blur is ordinary image code, and the
decision that a photograph is fit to show belongs to the brand.
"""

from __future__ import annotations

import logging
from dataclasses import asdict
from typing import Any

from sqlalchemy.orm import Session

from ..ai import availability, images
from ..ai.features import logo_detection
from ..ai.logo_regions import Box, clip, pad
from ..core.errors import AiUnavailable, Conflict, NotFound, ValidationFailed
from ..models import Brand, Lot, LotPhoto, User
from ..models.base import utcnow
from ..models.enums import LotStatus, PhotoKind, PhotoProtectionStatus, Visibility
from ..storage import build_key, delete_object, put_object, read_object
from . import audit_service

logger = logging.getLogger(__name__)

# A second inspection of these would spend money to repeat a known answer. The
# brand can still change the outcome in review.
_ALREADY_INSPECTED = frozenset(
    {
        PhotoProtectionStatus.CLEAR,
        PhotoProtectionStatus.BLURRED,
        PhotoProtectionStatus.NEEDS_REVIEW,
    }
)


def buyer_file_key(lot: Lot, photo: LotPhoto) -> str | None:
    """The stored object a buyer may receive, or None when it is withheld."""
    if Visibility(lot.visibility) != Visibility.UNBRANDED:
        return photo.file_key
    if photo.protection_reviewed_at is None:
        return None

    status = PhotoProtectionStatus(photo.protection_status)
    if status == PhotoProtectionStatus.CLEAR:
        return photo.file_key
    if status == PhotoProtectionStatus.BLURRED:
        return photo.blurred_file_key
    return None


def buyer_photos(lot: Lot) -> list[LotPhoto]:
    """The photographs a buyer may see, in gallery order."""
    ordered = sorted(lot.photos, key=lambda photo: photo.sort_order)
    return [photo for photo in ordered if buyer_file_key(lot, photo) is not None]


def problems(db: Session, lot: Lot) -> list[str]:
    """What still stands between this lot and being shown as unbranded."""
    if Visibility(lot.visibility) != Visibility.UNBRANDED:
        return []

    found: list[str] = []
    outstanding = [photo for photo in lot.photos if buyer_file_key(lot, photo) is None]
    if outstanding:
        found.append(
            f"{len(outstanding)} photograph(s) have not been reviewed for brand marks, "
            f"so buyers cannot be shown them."
        )

    brand = db.get(Brand, lot.brand_id)
    text = f"{lot.title} {lot.description or ''}".casefold()
    if brand is not None and brand.name.casefold() in text:
        found.append("The title or description contains the brand name.")
    return found


def assert_ready(db: Session, lot: Lot) -> None:
    """Refuse to put an unbranded lot in front of buyers before it is safe."""
    found = problems(db, lot)
    if found:
        raise Conflict("This unbranded listing is not ready. " + " ".join(found))


def scan_lot(db: Session, *, lot: Lot, actor: User, ip: str | None = None) -> list[LotPhoto]:
    """Look for brand marks in every photograph not yet inspected.

    One model call per photograph, and only for unbranded lots, because each
    call costs money. A failed call marks that photograph and carries on, so
    one bad image does not lose the work done on the others.
    """
    if Visibility(lot.visibility) != Visibility.UNBRANDED:
        raise Conflict("Only unbranded listings need their photographs checked for brand marks.")

    brand = db.get(Brand, lot.brand_id)
    if brand is None:
        raise NotFound("That brand does not exist.")

    counts = {status.value: 0 for status in PhotoProtectionStatus}
    for photo in sorted(lot.photos, key=lambda item: item.sort_order):
        status = PhotoProtectionStatus(photo.protection_status)
        if photo.protection_reviewed_at is None and status not in _ALREADY_INSPECTED:
            _inspect(db, lot=lot, photo=photo, brand=brand, actor=actor)
        counts[PhotoProtectionStatus(photo.protection_status).value] += 1
    db.flush()

    audit_service.record(
        db,
        action="lot.photos_scanned_for_marks",
        entity_type="lot",
        entity_id=lot.id,
        brand_id=lot.brand_id,
        actor_user_id=actor.id,
        actor_role=actor.role,
        after={"statuses": counts},
        ip=ip,
    )
    return sorted(lot.photos, key=lambda item: item.sort_order)


def review_photo(
    db: Session,
    *,
    lot: Lot,
    photo_id: str,
    actor: User,
    regions: list[Box] | None,
    ip: str | None = None,
) -> LotPhoto:
    """Record the brand's decision on one photograph.

    ``regions`` of None accepts the current result. A list replaces it with the
    regions the brand chose, and an empty list states that the photograph shows
    no brand mark.
    """
    if LotStatus(lot.status) == LotStatus.SOLD:
        raise Conflict("This lot has been sold, so its photographs can no longer change.")

    photo = next((item for item in lot.photos if item.id == photo_id), None)
    if photo is None:
        raise NotFound("That photograph is not on this lot.")

    before = {
        "status": PhotoProtectionStatus(photo.protection_status).value,
        "reviewed": photo.protection_reviewed_at is not None,
    }

    if regions is None:
        status = PhotoProtectionStatus(photo.protection_status)
        if status not in (PhotoProtectionStatus.CLEAR, PhotoProtectionStatus.BLURRED):
            raise ValidationFailed(
                "This photograph has no finished result to accept. Mark the areas to "
                "hide, or confirm that it shows no brand mark."
            )
    else:
        boxes = [pad(clip(box)) for box in regions]
        _store_result(
            lot=lot,
            photo=photo,
            original=read_object(photo.file_key),
            boxes=boxes,
            status=PhotoProtectionStatus.BLURRED if boxes else PhotoProtectionStatus.CLEAR,
        )
        photo.protection_detail = {
            "source": "brand",
            "regions": [asdict(box) for box in regions],
        }

    photo.protection_reviewed_at = utcnow()
    photo.protection_reviewed_by_user_id = actor.id
    db.flush()

    audit_service.record(
        db,
        action="lot.photo_protection_reviewed",
        entity_type="lot_photo",
        entity_id=photo.id,
        brand_id=lot.brand_id,
        actor_user_id=actor.id,
        actor_role=actor.role,
        before=before,
        after={
            "lot_id": lot.id,
            "status": PhotoProtectionStatus(photo.protection_status).value,
            "regions_chosen_by_brand": len(regions) if regions is not None else None,
        },
        ip=ip,
    )
    return photo


def _inspect(db: Session, *, lot: Lot, photo: LotPhoto, brand: Brand, actor: User) -> None:
    try:
        original = read_object(photo.file_key)
        outcome = logo_detection.detect(
            db,
            image=original,
            photo_kind=PhotoKind(photo.kind),
            brand_name=brand.name,
            brand_id=lot.brand_id,
            user_id=actor.id,
            photo_id=photo.id,
        )
    except AiUnavailable as exc:
        # No model today. The photograph stays withheld from buyers and goes
        # to the brand to mark its logos by hand, the same review it gets when
        # the model is unsure.
        photo.protection_status = PhotoProtectionStatus.NEEDS_REVIEW
        photo.protection_detail = {"source": "manual", "message": availability.reason(exc)}
        return
    # Deliberately broad. Whatever went wrong, the safe result is the same: the
    # photograph stays withheld and the rest of the lot still gets checked.
    except Exception as exc:
        logger.warning("mark inspection failed for photo %s: %s", photo.id, exc)
        photo.protection_status = PhotoProtectionStatus.FAILED
        photo.protection_detail = {"source": "model", "error": "The check could not finish."}
        return

    if outcome.needs_review:
        status = PhotoProtectionStatus.NEEDS_REVIEW
    elif outcome.blur_boxes:
        status = PhotoProtectionStatus.BLURRED
    else:
        status = PhotoProtectionStatus.CLEAR

    _store_result(lot=lot, photo=photo, original=original, boxes=outcome.blur_boxes, status=status)
    detail: dict[str, Any] = {
        "source": "model",
        "ai_output_id": outcome.result.output_id,
        "regions": [region.model_dump() for region in outcome.detection.regions],
        "review_reasons": outcome.review_reasons,
    }
    photo.protection_detail = detail


def _store_result(
    *,
    lot: Lot,
    photo: LotPhoto,
    original: bytes,
    boxes: list[Box],
    status: PhotoProtectionStatus,
) -> None:
    previous = photo.blurred_file_key
    photo.blurred_file_key = None
    if boxes:
        key = build_key(prefix="protected", brand_id=lot.brand_id, content_type="image/jpeg")
        put_object(key, images.blur_regions(original, boxes), "image/jpeg")
        photo.blurred_file_key = key
    photo.protection_status = status

    if previous:
        try:
            delete_object(previous)
        except Exception:
            logger.warning("could not delete replaced protected photo %s", previous)
