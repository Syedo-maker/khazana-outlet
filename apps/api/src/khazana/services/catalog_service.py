"""Lot creation, the manifest, the photo pipeline and the lot state machine.

This is M3. Four things live here, and they are together because they are the
same promise seen from different angles: what a buyer is told about a lot has
to be what the brand actually agreed to sell.

1. **The state machine.** One transition table, at the top of this module.
   Every status change in the platform goes through `transition`, including
   the approval actions in `approval_service`. A status set by assignment
   somewhere else is a bug, because the table is the only place that knows
   which moves are legal.

2. **The manifest rule.** The sum of the lines must equal the stated total.
   The schema docstring explains why it is enforced in three places; this
   module is the first of them, and the only one that produces a sentence a
   brand can act on rather than a constraint violation.

3. **The photo pipeline.** Nothing is stored as uploaded. Every photograph is
   resized and recompressed on the way in, because image tokens dominate the
   cost of the Phase 2 vision call and a 4000 pixel phone photograph produces
   the same draft as a 1024 pixel one at several times the price.

4. **Edits after approval.** A brand approves a specific payload. Changing the
   price or the piece count of an approved lot sends it back for approval
   rather than quietly altering what a buyer is looking at. `MATERIAL_FIELDS`
   is the list of changes that trigger that, and getting it wrong in either
   direction is a real failure: too wide and brands re-approve constantly, too
   narrow and the approval record stops meaning anything.

The AI boundary, from `docs/ai-architecture.md` section 2: the Phase 2
features called from here draft and suggest. They never set a status, never
set a price and never approve. `draft_for_lot` writes to the draft fields of a
lot the brand can still edit, and that is the whole of its authority.
"""

from __future__ import annotations

import logging
import secrets
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import ColumnElement, func, select
from sqlalchemy.orm import Session, selectinload

from ..ai import images
from ..ai.features import manifest_extract
from ..core.errors import Conflict, NotFound, ValidationFailed
from ..models import (
    Brand,
    BrandPolicy,
    Category,
    Lot,
    LotDefect,
    LotPhoto,
    ManifestLine,
    User,
)
from ..models.enums import ConditionGrade, LotStatus, PhotoKind
from ..storage import (
    ALLOWED_IMAGE_TYPES,
    StorageError,
    build_key,
    checksum,
    delete_object,
    put_object,
    validate_upload,
)
from . import audit_service, brand_service

logger = logging.getLogger(__name__)


# ------------------------------------------------------------ state machine

# The legal moves. Read it as "from this status, these are allowed".
#
# Two entries are worth explaining because they look like mistakes:
#
# - PENDING_APPROVAL can go back to DRAFT. That is a rejection, and a rejected
#   listing has to be editable or the brand cannot act on the rejection note.
# - WITHDRAWN can go back to DRAFT. A brand that pulls a lot for the season
#   should be able to relist it next year without retyping the manifest.
# - APPROVED and PAUSED can go back to DRAFT. That is what a material edit
#   does: the brand approved a specific price and piece count, so changing
#   either costs the approval. Without these two entries the MATERIAL_FIELDS
#   rule below cannot fire at all, which is how it was first written and what
#   the state machine tests caught.
#
# SOLD and EXPIRED are terminal on purpose. Reviving a sold lot would let the
# same stock be sold twice, and that is the one bug a marketplace cannot have.
TRANSITIONS: dict[LotStatus, frozenset[LotStatus]] = {
    LotStatus.DRAFT: frozenset({LotStatus.PENDING_APPROVAL, LotStatus.WITHDRAWN}),
    LotStatus.PENDING_APPROVAL: frozenset(
        {LotStatus.APPROVED, LotStatus.DRAFT, LotStatus.WITHDRAWN}
    ),
    LotStatus.APPROVED: frozenset(
        {LotStatus.LIVE, LotStatus.DRAFT, LotStatus.WITHDRAWN, LotStatus.EXPIRED}
    ),
    LotStatus.LIVE: frozenset(
        {LotStatus.PAUSED, LotStatus.SOLD, LotStatus.WITHDRAWN, LotStatus.EXPIRED}
    ),
    LotStatus.PAUSED: frozenset(
        {LotStatus.LIVE, LotStatus.DRAFT, LotStatus.WITHDRAWN, LotStatus.EXPIRED}
    ),
    LotStatus.WITHDRAWN: frozenset({LotStatus.DRAFT}),
    LotStatus.SOLD: frozenset(),
    LotStatus.EXPIRED: frozenset({LotStatus.DRAFT}),
}

# Statuses in which a brand may still edit the listing freely. Anything else
# goes through `_guard_material_change`.
EDITABLE_STATUSES = frozenset({LotStatus.DRAFT, LotStatus.PENDING_APPROVAL})

# Statuses where a material edit is allowed but costs the approval. A paused
# lot is included because pausing is what a brand does in order to change
# something, and the error message on a live lot tells them to pause first.
RESETTABLE_STATUSES = frozenset({LotStatus.APPROVED, LotStatus.PAUSED})

# Changing any of these after approval invalidates the approval, because each
# one changes what the buyer is being sold or what it costs. `available_until`
# and `season` are deliberately absent: shortening a window or correcting a
# season label does not change the goods.
MATERIAL_FIELDS = frozenset(
    {
        "title",
        "description",
        "category_id",
        "condition_grade",
        "total_pieces",
        "retail_price_per_piece_pkr",
        "lot_price_pkr",
        "min_order_pieces",
        "stock_city",
        "expiry_date",
    }
)

LOT_AUDIT_FIELDS = (
    "lot_code",
    "title",
    "category_id",
    "condition_grade",
    "total_pieces",
    "retail_price_per_piece_pkr",
    "lot_price_pkr",
    "min_order_pieces",
    "stock_city",
    "status",
    "visibility",
    "expiry_date",
    "available_until",
)

# Fields a brand may set directly. `status`, `visibility`, `approved_at`,
# `lot_code` and `brand_id` are all absent: each has its own entry point with
# its own rules, and allowing them here would route around those rules.
EDITABLE_FIELDS = frozenset(
    {
        "title",
        "description",
        "season",
        "category_id",
        "condition_grade",
        "total_pieces",
        "retail_price_per_piece_pkr",
        "lot_price_pkr",
        "min_order_pieces",
        "stock_city",
        "weight_kg",
        "cartons",
        "expiry_date",
        "available_until",
    }
)

MAX_PHOTOS_PER_LOT = 12
# Three is the floor a buyer needs to judge a lot: the stock as a whole, one
# garment, and the label. Below that the listing is a guess.
MIN_PHOTOS_TO_SUBMIT = 3
MAX_MANIFEST_LINES = 500

# Codes get read aloud and typed by hand on WhatsApp, which is the main sales
# channel in this market, so the alphabet leaves out every character that is
# confusable in a hurry: O and 0, I, L and 1, S and 5.
_CODE_ALPHABET = "ABCDEFGHJKMNPQRTUVWXYZ2346789"


@dataclass(slots=True)
class ManifestImport:
    """What a bulk upload produced, before the brand accepts it.

    Nothing here has been saved. `rows` is a proposal for the editor to show,
    and `warnings` is everything the brand should look at before accepting it.
    """

    rows: list[dict[str, object]] = field(default_factory=list)
    total_pieces: int = 0
    # What the spreadsheet itself claimed the total was, when it said so. A
    # mismatch between this and total_pieces means the brand's own file does
    # not add up, which is worth showing rather than quietly correcting.
    declared_total: int | None = None
    confidence: float = 0.0
    warnings: list[str] = field(default_factory=list)
    model: str = ""
    from_fixture: bool = False
    cost_usd: float = 0.0


@dataclass(slots=True)
class Readiness:
    """Whether a lot can be submitted, and what is missing if not."""

    blockers: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def ready(self) -> bool:
        return not self.blockers


def transition(
    db: Session,
    *,
    lot: Lot,
    to: LotStatus,
    actor: User | None,
    note: str | None = None,
    ip: str | None = None,
) -> Lot:
    """Move a lot to a new status, or refuse with a readable reason.

    Every status change goes through here. The audit entry is written in the
    same transaction as the change, so a rolled back transition cannot leave a
    log claiming it happened.
    """
    current = LotStatus(lot.status)
    if to == current:
        return lot

    allowed = TRANSITIONS.get(current, frozenset())
    if to not in allowed:
        if not allowed:
            raise Conflict(f"This lot is {current.value} and cannot change state any further.")
        readable = ", ".join(sorted(status.value for status in allowed))
        raise Conflict(
            f"A {current.value} lot cannot become {to.value}. From here it can only "
            f"become: {readable}."
        )

    before = audit_service.snapshot(lot, LOT_AUDIT_FIELDS)
    lot.status = to
    db.flush()
    after = audit_service.snapshot(lot, LOT_AUDIT_FIELDS)

    audit_service.record(
        db,
        action=f"lot.{to.value}",
        entity_type="lot",
        entity_id=lot.id,
        brand_id=lot.brand_id,
        actor_user_id=actor.id if actor else None,
        actor_role=actor.role if actor else None,
        actor_kind=audit_service.ACTOR_USER if actor else audit_service.ACTOR_SYSTEM,
        before=before,
        after=audit_service.diff(before, after),
        note=note,
        ip=ip,
    )
    return lot


# --------------------------------------------------------------------- lots


def new_lot_code(db: Session) -> str:
    """A short, human readable, unique code.

    Random rather than sequential. A sequential code tells every competitor
    how many lots the platform has listed this month, and on a marketplace
    that is still small that is not information worth publishing.
    """
    for _ in range(12):
        candidate = "LOT-" + "".join(secrets.choice(_CODE_ALPHABET) for _ in range(7))
        if db.scalars(select(Lot.id).where(Lot.lot_code == candidate)).first() is None:
            return candidate
    # 29^7 is about 17 billion, so twelve collisions in a row means the random
    # source is broken rather than unlucky. Failing loudly beats looping.
    raise Conflict("Could not allocate a lot code. Try again.")


def create_lot(
    db: Session,
    *,
    brand_id: str,
    actor: User,
    data: dict[str, Any],
    ip: str | None = None,
) -> Lot:
    """Create a draft lot.

    Starts in DRAFT with the brand's default protection level. Nothing is
    visible to a buyer until it has been through approval, which the schema
    enforces with a CHECK constraint as well.
    """
    brand = db.get(Brand, brand_id)
    if brand is None or brand.is_deleted:
        raise NotFound("That brand does not exist.")

    rejected = set(data) - EDITABLE_FIELDS
    if rejected:
        raise ValidationFailed(f"These fields cannot be set here: {sorted(rejected)}.")

    category = _require_category(db, str(data.get("category_id", "")))
    _validate_commercials(db, brand_id=brand_id, data=data)
    _validate_expiry(category, data.get("expiry_date"))

    lot = Lot(
        lot_code=new_lot_code(db),
        brand_id=brand_id,
        status=LotStatus.DRAFT,
        visibility=brand_service.default_visibility_for(db, brand_id),
        created_by_user_id=actor.id,
        **data,
    )
    db.add(lot)
    db.flush()

    audit_service.record(
        db,
        action="lot.created",
        entity_type="lot",
        entity_id=lot.id,
        brand_id=brand_id,
        actor_user_id=actor.id,
        actor_role=actor.role,
        after=audit_service.snapshot(lot, LOT_AUDIT_FIELDS),
        ip=ip,
    )
    return lot


def update_lot(
    db: Session,
    *,
    lot: Lot,
    actor: User,
    changes: dict[str, Any],
    ip: str | None = None,
) -> Lot:
    """Edit a lot, sending it back for approval if the change is material."""
    rejected = set(changes) - EDITABLE_FIELDS
    if rejected:
        raise ValidationFailed(f"These fields cannot be changed here: {sorted(rejected)}.")
    if not changes:
        return lot

    _guard_material_change(lot, changes)

    if "category_id" in changes:
        category = _require_category(db, str(changes["category_id"]))
    else:
        category = _require_category(db, lot.category_id)

    merged = {
        "total_pieces": lot.total_pieces,
        "retail_price_per_piece_pkr": lot.retail_price_per_piece_pkr,
        "lot_price_pkr": lot.lot_price_pkr,
        "min_order_pieces": lot.min_order_pieces,
        **changes,
    }
    _validate_commercials(db, brand_id=lot.brand_id, data=merged)
    _validate_expiry(category, merged.get("expiry_date", lot.expiry_date))

    before = audit_service.snapshot(lot, LOT_AUDIT_FIELDS)
    for name, value in changes.items():
        setattr(lot, name, value)
    db.flush()

    # Reducing the total below what the manifest already describes would leave
    # the lot inconsistent, so it is refused here rather than at the trigger.
    if "total_pieces" in changes and lot.manifest_lines and not lot.is_manifest_balanced:
        raise ValidationFailed(
            f"The manifest lists {lot.manifest_total} pieces, so the total cannot be "
            f"{lot.total_pieces}. Change the manifest first, or make the total "
            f"{lot.manifest_total}."
        )

    db.refresh(lot)
    after = audit_service.snapshot(lot, LOT_AUDIT_FIELDS)
    audit_service.record(
        db,
        action="lot.updated",
        entity_type="lot",
        entity_id=lot.id,
        brand_id=lot.brand_id,
        actor_user_id=actor.id,
        actor_role=actor.role,
        before=before,
        after=audit_service.diff(before, after),
        ip=ip,
    )

    material = sorted(set(changes) & MATERIAL_FIELDS)
    if material and LotStatus(lot.status) in RESETTABLE_STATUSES:
        transition(
            db,
            lot=lot,
            to=LotStatus.DRAFT,
            actor=actor,
            note=f"Approval reset by a change to: {', '.join(material)}.",
            ip=ip,
        )
    return lot


def get_lot(db: Session, lot_id: str) -> Lot:
    """Load a lot with everything a listing page needs, in one round trip.

    Callers are responsible for the tenant check. Every endpoint in the
    catalog router calls `assert_owns` on the result, and the buyer facing
    paths in `approval_service` apply the visibility rules instead.
    """
    lot = db.scalars(
        select(Lot)
        .where(Lot.id == lot_id)
        .options(
            selectinload(Lot.manifest_lines),
            selectinload(Lot.photos),
            selectinload(Lot.defects),
            selectinload(Lot.excluded_cities),
        )
    ).first()
    if lot is None or lot.is_deleted:
        raise NotFound("That lot does not exist.")
    return lot


# ------------------------------------------------------------------ manifest


def set_manifest(
    db: Session,
    *,
    lot: Lot,
    actor: User,
    lines: list[dict[str, Any]],
    ip: str | None = None,
) -> list[ManifestLine]:
    """Replace the manifest in one shot.

    Replace rather than patch, because the editor sends the whole table and a
    per row API would let a half applied edit leave the sum wrong between
    requests. The balance rule is checked before anything is written.
    """
    _require_editable(lot, "The manifest")

    if not lines:
        raise ValidationFailed("A manifest needs at least one line.")
    if len(lines) > MAX_MANIFEST_LINES:
        raise ValidationFailed(
            f"{len(lines)} lines is more than the {MAX_MANIFEST_LINES} this editor "
            f"supports. Split the stock into several lots."
        )

    cleaned: list[tuple[str, str, int]] = []
    seen: set[tuple[str, str]] = set()
    for index, raw in enumerate(lines, start=1):
        size = str(raw.get("size", "")).strip()
        color = str(raw.get("color", "")).strip()
        if not size or not color:
            raise ValidationFailed(f"Line {index} needs both a size and a colour.")
        try:
            pieces = int(raw.get("pieces", 0))
        except (TypeError, ValueError):
            raise ValidationFailed(
                f"Line {index} has {raw.get('pieces')!r} pieces, which is not a number."
            ) from None
        if pieces <= 0:
            raise ValidationFailed(
                f"Line {index} has {pieces} pieces. Every line needs at least 1."
            )

        key = (size.casefold(), color.casefold())
        if key in seen:
            raise ValidationFailed(
                f"Size {size} in {color} appears twice. Combine them into one line."
            )
        seen.add(key)
        cleaned.append((size, color, pieces))

    total = sum(pieces for _, _, pieces in cleaned)
    if total != lot.total_pieces:
        difference = total - lot.total_pieces
        direction = "more than" if difference > 0 else "less than"
        raise ValidationFailed(
            f"The manifest adds up to {total} pieces, which is {abs(difference)} "
            f"{direction} the lot total of {lot.total_pieces}. Buyers reject lots "
            f"whose manifest does not match, so these have to agree."
        )

    before = {"lines": len(lot.manifest_lines), "pieces": lot.manifest_total}

    # Delete through the relationship so the cascade handles the orphans. A
    # bulk DELETE would leave the already loaded collection stale.
    lot.manifest_lines.clear()
    db.flush()
    for size, color, pieces in cleaned:
        lot.manifest_lines.append(
            ManifestLine(brand_id=lot.brand_id, size=size, color=color, pieces=pieces)
        )
    db.flush()

    audit_service.record(
        db,
        action="lot.manifest_set",
        entity_type="lot",
        entity_id=lot.id,
        brand_id=lot.brand_id,
        actor_user_id=actor.id,
        actor_role=actor.role,
        before=before,
        after={"lines": len(cleaned), "pieces": total},
        ip=ip,
    )
    return list(lot.manifest_lines)


def import_manifest(
    db: Session,
    *,
    lot: Lot,
    actor: User,
    data: bytes,
    filename: str,
    ip: str | None = None,
) -> ManifestImport:
    """Read a spreadsheet into manifest rows, without saving them.

    Deliberately does not write. A brand reviews what the extractor produced
    and then calls `set_manifest`, because an AI reading of someone's
    spreadsheet is a suggestion and the manifest is a commitment. That split
    is the AI boundary from `docs/ai-architecture.md` section 2, expressed as
    two endpoints.
    """
    _require_editable(lot, "The manifest")

    # extract() reads the file, calls the model and merges duplicate size and
    # colour pairs itself, so there is nothing to pre-process here. A bad file
    # raises ValueError from read_table, which is a 422 rather than a 500.
    try:
        outcome = manifest_extract.extract(
            db,
            data=data,
            filename=filename,
            brand_id=lot.brand_id,
            user_id=actor.id,
            lot_id=lot.id,
        )
    except ValueError as exc:
        raise ValidationFailed(str(exc)) from exc

    rows = manifest_extract.to_manifest_rows(outcome, lot_id=lot.id, brand_id=lot.brand_id)

    # The extractor reports against the total written in the file. The lot has
    # its own total, and that is the one the manifest has to match, so the
    # comparison is made again here.
    warnings = [*outcome.notes, *outcome.corrections]
    if outcome.line_total != lot.total_pieces:
        difference = outcome.line_total - lot.total_pieces
        warnings.append(
            f"The sheet adds up to {outcome.line_total} pieces and this lot is "
            f"{lot.total_pieces}, a difference of {difference:+d}. Nothing has been "
            f"saved. Fix the rows or the lot total before saving."
        )

    audit_service.record(
        db,
        action="lot.manifest_imported",
        entity_type="lot",
        entity_id=lot.id,
        brand_id=lot.brand_id,
        actor_user_id=actor.id,
        actor_role=actor.role,
        after={
            "rows_extracted": len(rows),
            "pieces": outcome.line_total,
            "declared_total": outcome.declared_total,
            "confidence": outcome.confidence,
            "model": outcome.result.model,
            "from_fixture": outcome.result.from_fixture,
        },
        note=f"Imported from {filename}",
        ip=ip,
    )

    return ManifestImport(
        rows=rows,
        total_pieces=outcome.line_total,
        declared_total=outcome.declared_total,
        confidence=outcome.confidence,
        warnings=warnings,
        model=outcome.result.model,
        from_fixture=outcome.result.from_fixture,
        cost_usd=float(outcome.result.cost_usd),
    )


# -------------------------------------------------------------------- photos


def add_photo(
    db: Session,
    *,
    lot: Lot,
    actor: User,
    data: bytes,
    content_type: str,
    kind: PhotoKind,
    ip: str | None = None,
) -> LotPhoto:
    """Validate, shrink, store and record one photograph.

    The order matters. Validation happens on the bytes as uploaded, so a file
    pretending to be an image is rejected before any processing touches it.
    Only then is it resized, and only the resized version is ever stored: the
    original is not kept, because nothing in the product uses it and a folder
    of 8 MB phone photographs is a storage bill with no reader.
    """
    _require_editable(lot, "Photographs")

    if len(lot.photos) >= MAX_PHOTOS_PER_LOT:
        raise ValidationFailed(
            f"This lot already has {MAX_PHOTOS_PER_LOT} photographs, which is the limit. "
            f"Remove one first."
        )

    try:
        validate_upload(data, content_type, allowed=ALLOWED_IMAGE_TYPES)
    except StorageError as exc:
        raise ValidationFailed(str(exc)) from exc

    digest = checksum(data)
    duplicate = next((p for p in lot.photos if p.checksum == digest), None)
    if duplicate is not None:
        raise ValidationFailed(
            f"That is the same image as the existing {duplicate.kind} photograph."
        )

    try:
        prepared = images.prepare(data)
    except images.ImageError as exc:
        raise ValidationFailed(f"That image could not be processed: {exc}") from exc

    # prepare() always returns JPEG, whatever came in, so the stored object is
    # described as JPEG rather than as the uploaded type.
    key = build_key(prefix="lots", brand_id=lot.brand_id, content_type="image/jpeg")
    put_object(key, prepared.data, "image/jpeg")

    next_order = 1 + max((p.sort_order for p in lot.photos), default=0)
    photo = LotPhoto(
        brand_id=lot.brand_id,
        file_key=key,
        kind=kind,
        sort_order=next_order,
        width=prepared.width,
        height=prepared.height,
        bytes_stored=len(prepared.data),
        checksum=digest,
        is_optimised=True,
    )
    # Appended through the relationship rather than added to the session. A
    # bare db.add leaves the already loaded lot.photos collection stale, and
    # then the readiness check counts the photographs as missing and the
    # duplicate check stops seeing earlier uploads. The rest of this module
    # goes through the relationship for the same reason.
    lot.photos.append(photo)
    db.flush()

    audit_service.record(
        db,
        action="lot.photo_added",
        entity_type="lot_photo",
        entity_id=photo.id,
        brand_id=lot.brand_id,
        actor_user_id=actor.id,
        actor_role=actor.role,
        after={
            "lot_id": lot.id,
            "kind": kind.value,
            "bytes_uploaded": prepared.original_bytes,
            "bytes_stored": len(prepared.data),
            "saved_bytes": prepared.saved_bytes,
        },
        ip=ip,
    )
    return photo


def reorder_photos(
    db: Session,
    *,
    lot: Lot,
    actor: User,
    photo_ids: list[str],
    ip: str | None = None,
) -> list[LotPhoto]:
    """Set the display order. The first photograph is the one buyers see.

    The full set has to be supplied. A partial reorder would leave the rest at
    whatever order they had, which in practice means duplicate positions and a
    gallery whose order depends on how the database felt about the query.
    """
    _require_editable(lot, "Photographs")

    existing = {photo.id: photo for photo in lot.photos}
    if set(photo_ids) != set(existing) or len(photo_ids) != len(existing):
        raise ValidationFailed(
            f"Send all {len(existing)} photograph identifiers exactly once, in the "
            f"order you want them shown."
        )

    for position, photo_id in enumerate(photo_ids, start=1):
        existing[photo_id].sort_order = position
    db.flush()

    audit_service.record(
        db,
        action="lot.photos_reordered",
        entity_type="lot",
        entity_id=lot.id,
        brand_id=lot.brand_id,
        actor_user_id=actor.id,
        actor_role=actor.role,
        after={"order": photo_ids},
        ip=ip,
    )
    return sorted(existing.values(), key=lambda p: p.sort_order)


def remove_photo(
    db: Session,
    *,
    lot: Lot,
    actor: User,
    photo_id: str,
    ip: str | None = None,
) -> None:
    """Delete a photograph and close the gap in the ordering."""
    _require_editable(lot, "Photographs")

    photo = next((p for p in lot.photos if p.id == photo_id), None)
    if photo is None:
        raise NotFound("That photograph is not on this lot.")

    # A defect photograph is referenced by the defect row. Removing it would
    # leave a defect the buyer cannot see, which is the opposite of the point.
    if any(defect.photo_id == photo_id for defect in lot.defects):
        raise Conflict(
            "That photograph is the evidence for a listed defect. Remove the defect "
            "first if it no longer applies."
        )

    key = photo.file_key
    lot.photos.remove(photo)
    db.flush()

    for position, remaining in enumerate(sorted(lot.photos, key=lambda p: p.sort_order), start=1):
        remaining.sort_order = position
    db.flush()

    audit_service.record(
        db,
        action="lot.photo_removed",
        entity_type="lot_photo",
        entity_id=photo_id,
        brand_id=lot.brand_id,
        actor_user_id=actor.id,
        actor_role=actor.role,
        before={"lot_id": lot.id, "file_key": key},
        ip=ip,
    )

    # Storage last. If the object delete fails the row is already gone, which
    # leaves an orphaned file: wasted bytes, and nothing a buyer can reach. The
    # other order risks a listing pointing at a file that is no longer there.
    try:
        delete_object(key)
    except Exception:
        logger.warning("could not delete stored object %s for lot %s", key, lot.id)


# ------------------------------------------------------------------- defects


def set_defects(
    db: Session,
    *,
    lot: Lot,
    actor: User,
    defects: list[dict[str, Any]],
    ip: str | None = None,
) -> list[LotDefect]:
    """Replace the itemised defect list.

    Grade C means visible defects, and the roadmap requires each one itemised.
    An unmentioned defect found by a buyer loses that buyer permanently, so the
    piece counts are checked against the lot rather than taken on trust.
    """
    _require_editable(lot, "Defects")

    photo_ids = {photo.id for photo in lot.photos}
    cleaned: list[dict[str, Any]] = []
    for index, raw in enumerate(defects, start=1):
        issue = str(raw.get("issue", "")).strip()
        if not issue:
            raise ValidationFailed(f"Defect {index} needs a description.")
        try:
            affected = int(raw.get("pieces_affected", 0))
        except (TypeError, ValueError):
            raise ValidationFailed(
                f"Defect {index} affects {raw.get('pieces_affected')!r} pieces, which "
                f"is not a number."
            ) from None
        if affected <= 0:
            raise ValidationFailed(f"Defect {index} has to affect at least 1 piece.")
        if affected > lot.total_pieces:
            raise ValidationFailed(
                f"Defect {index} affects {affected} pieces but the lot only has {lot.total_pieces}."
            )
        photo_id = raw.get("photo_id")
        if photo_id is not None and str(photo_id) not in photo_ids:
            raise ValidationFailed(
                f"Defect {index} points at a photograph that is not on this lot."
            )
        cleaned.append(
            {
                "issue": issue[:255],
                "pieces_affected": affected,
                "photo_id": str(photo_id) if photo_id else None,
            }
        )

    before = {"count": len(lot.defects)}
    lot.defects.clear()
    db.flush()
    for entry in cleaned:
        lot.defects.append(LotDefect(brand_id=lot.brand_id, **entry))
    db.flush()

    audit_service.record(
        db,
        action="lot.defects_set",
        entity_type="lot",
        entity_id=lot.id,
        brand_id=lot.brand_id,
        actor_user_id=actor.id,
        actor_role=actor.role,
        before=before,
        after={"count": len(cleaned), "defects": cleaned},
        ip=ip,
    )
    return list(lot.defects)


# ---------------------------------------------------------------- submission


def readiness(db: Session, lot: Lot) -> Readiness:
    """What still stands between this lot and a buyer seeing it.

    Returned rather than raised, so the editor can show a checklist while the
    brand works through it instead of one error at a time. `submit_for_approval`
    turns the same list into a refusal.
    """
    result = Readiness()

    if not lot.manifest_lines:
        result.blockers.append("The manifest is empty.")
    elif not lot.is_manifest_balanced:
        result.blockers.append(
            f"The manifest adds up to {lot.manifest_total} pieces, not {lot.total_pieces}."
        )

    if len(lot.photos) < MIN_PHOTOS_TO_SUBMIT:
        result.blockers.append(
            f"{len(lot.photos)} of the {MIN_PHOTOS_TO_SUBMIT} required photographs "
            f"have been uploaded."
        )

    kinds = {PhotoKind(photo.kind) for photo in lot.photos}
    if PhotoKind.LABEL not in kinds:
        result.warnings.append(
            "No label photograph. Buyers ask for one before almost every bulk order."
        )

    if ConditionGrade(lot.condition_grade) == ConditionGrade.C and not lot.defects:
        result.blockers.append("Grade C means visible defects, so each one has to be listed.")

    category = db.get(Category, lot.category_id)
    if category is not None and category.requires_expiry and lot.expiry_date is None:
        result.blockers.append(f"{category.name} needs an expiry date.")

    if not lot.description:
        result.warnings.append("No description. The photo to listing feature can draft one.")

    return result


def submit_for_approval(db: Session, *, lot: Lot, actor: User, ip: str | None = None) -> Lot:
    """Send a draft to the brand for approval.

    The readiness checks run here rather than at approval time on purpose. An
    owner reviewing a queue should be deciding on a complete listing, not
    discovering that the manifest is short.
    """
    state = readiness(db, lot)
    if not state.ready:
        raise ValidationFailed("This lot is not ready to submit. " + " ".join(state.blockers))
    return transition(db, lot=lot, to=LotStatus.PENDING_APPROVAL, actor=actor, ip=ip)


# -------------------------------------------------------------------- queries


def list_lots(
    db: Session,
    *,
    brand_ids: list[str] | None,
    status: LotStatus | None = None,
    search: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[Lot], int]:
    """The brand's own lots, newest first, with a total for paging.

    `brand_ids` of None means every brand and is for admin callers only. The
    router decides that; this function does not know who is asking.
    """
    # Annotated, because mypy infers the narrow type of the first element
    # and then rejects the OR clause appended for the search term.
    conditions: list[ColumnElement[bool]] = [Lot.deleted_at.is_(None)]
    if brand_ids is not None:
        if not brand_ids:
            return [], 0
        conditions.append(Lot.brand_id.in_(brand_ids))
    if status is not None:
        conditions.append(Lot.status == status)
    if search:
        term = f"%{search.strip()}%"
        conditions.append(Lot.title.ilike(term) | Lot.lot_code.ilike(term))

    total = db.scalar(select(func.count()).select_from(Lot).where(*conditions)) or 0
    rows = list(
        db.scalars(
            select(Lot)
            .where(*conditions)
            .options(selectinload(Lot.photos), selectinload(Lot.manifest_lines))
            .order_by(Lot.created_at.desc())
            .limit(min(limit, 200))
            .offset(max(offset, 0))
        ).all()
    )
    return rows, int(total)


# -------------------------------------------------------------------- guards


def _require_category(db: Session, category_id: str) -> Category:
    category = db.get(Category, category_id)
    if category is None:
        raise ValidationFailed("Choose a category from the list.")
    if category.children:
        raise ValidationFailed(
            f"{category.name} is a top level category. Choose one of its subcategories."
        )
    return category


def _validate_expiry(category: Category, expiry: object) -> None:
    if category.requires_expiry and expiry is None:
        raise ValidationFailed(
            f"{category.name} has a shelf life, so this lot needs an expiry date."
        )


def _validate_commercials(db: Session, *, brand_id: str, data: dict[str, Any]) -> None:
    """Check the money and the piece counts against the brand's own policy.

    The database has CHECK constraints for all of this. They stay, because a
    background job or a direct SQL fix does not come through here. The point of
    repeating the checks is the error message: a brand that priced a lot above
    its own discount floor should be told which number to change.
    """
    total = int(data.get("total_pieces", 0) or 0)
    retail = int(data.get("retail_price_per_piece_pkr", 0) or 0)
    price = int(data.get("lot_price_pkr", 0) or 0)
    min_order = int(data.get("min_order_pieces", 0) or 0)

    if total <= 0:
        raise ValidationFailed("A lot needs at least 1 piece.")
    if retail <= 0:
        raise ValidationFailed("The retail price per piece has to be more than 0.")
    if price <= 0:
        raise ValidationFailed("The lot price has to be more than 0.")
    if min_order <= 0 or min_order > total:
        raise ValidationFailed(f"The minimum order has to be between 1 and {total} pieces.")

    retail_total = retail * total
    if price > retail_total:
        raise ValidationFailed(
            f"The lot price of {price:,} PKR is above the retail value of "
            f"{retail_total:,} PKR. Surplus stock sells below retail."
        )

    discount = round((1 - price / retail_total) * 100, 2)
    policy = db.scalars(select(BrandPolicy).where(BrandPolicy.brand_id == brand_id)).first()
    if policy is None:
        return

    if price < policy.min_lot_value_pkr:
        raise ValidationFailed(
            f"Your minimum lot value is {policy.min_lot_value_pkr:,} PKR and this lot "
            f"is {price:,} PKR."
        )
    low = float(policy.min_discount_percent)
    high = float(policy.max_discount_percent)
    if discount < low:
        raise ValidationFailed(
            f"That is a {discount:.0f} percent discount. Your floor is {low:.0f} percent, "
            f"so the lot price needs to be at most "
            f"{int(retail_total * (1 - low / 100)):,} PKR."
        )
    if discount > high:
        raise ValidationFailed(
            f"That is a {discount:.0f} percent discount, above your ceiling of "
            f"{high:.0f} percent. This guard exists so a pricing mistake cannot "
            f"undercut your own retail channel."
        )


def _require_editable(lot: Lot, what: str) -> None:
    status = LotStatus(lot.status)
    if status in EDITABLE_STATUSES:
        return
    if status in RESETTABLE_STATUSES:
        raise Conflict(
            f"{what} cannot be changed on a {status.value} lot, because it would "
            f"alter what was approved. Take the lot back to draft first, which "
            f"clears the approval, then submit it again."
        )
    raise Conflict(f"{what} cannot be changed on a {status.value} lot.")


def _guard_material_change(lot: Lot, changes: dict[str, Any]) -> None:
    """Refuse edits that a later status cannot absorb.

    DRAFT and PENDING_APPROVAL take anything. APPROVED and PAUSED take a
    material change and lose their approval, which `update_lot` handles. LIVE
    does not: a buyer may be looking at the listing or part way through an
    order, so the brand pauses first. Everything else is closed.
    """
    status = LotStatus(lot.status)
    if status in EDITABLE_STATUSES or status in RESETTABLE_STATUSES:
        return

    material = sorted(set(changes) & MATERIAL_FIELDS)
    if not material:
        return
    if status == LotStatus.LIVE:
        raise Conflict(
            f"This lot is live, so {', '.join(material)} cannot be changed underneath "
            f"a buyer. Pause it first, make the change, then approve it again."
        )
    raise Conflict(f"A {status.value} lot cannot be edited.")
