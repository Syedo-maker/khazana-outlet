"""Builders shared by the catalog and approval test modules.

A module rather than fixtures in `conftest.py`, because these are used as
default arguments and inside other helpers, which fixtures cannot be. The
tests directory has no `__init__.py`, so pytest puts it on `sys.path` and this
imports by plain name.

Not named `test_*`, so pytest does not try to collect it.
"""

from __future__ import annotations

import io
from datetime import UTC, datetime

from PIL import Image
from sqlalchemy.orm import Session

from khazana.models import Brand, Lot, User
from khazana.models.enums import ConditionGrade, LotStatus, PhotoKind
from khazana.services import approval_service, catalog_service

# retail 1000 x 100 pieces = 100,000 PKR at retail. A lot price of 30,000 is a
# 70 percent discount, inside the default 50 to 85 band, and above the 25,000
# default minimum lot value. Several tests depend on those numbers, so changing
# them means re-checking which guard fires first.
BASE_LOT: dict[str, object] = {
    "title": "Summer lawn, unstitched, mixed sizes",
    "condition_grade": ConditionGrade.A,
    "total_pieces": 100,
    "retail_price_per_piece_pkr": 1000,
    "lot_price_pkr": 30_000,
    "min_order_pieces": 10,
    "stock_city": "Lahore",
}


def jpeg_bytes(*, width: int = 1600, height: int = 1200, seed: int = 0) -> bytes:
    """A real JPEG, not a stub.

    The upload path sniffs magic bytes and then runs the image through Pillow,
    so a fake payload would exercise neither. `seed` changes the colour, which
    changes the bytes, which is what the duplicate check needs in order to
    tell two uploads apart.
    """
    buffer = io.BytesIO()
    colour = ((seed * 37) % 256, (seed * 91) % 256, (seed * 143) % 256)
    Image.new("RGB", (width, height), colour).save(buffer, format="JPEG")
    return buffer.getvalue()


def balanced_manifest(total: int = 100) -> list[dict[str, object]]:
    """Four lines adding up to the lot total."""
    per = total // 4
    return [
        {"size": "S", "color": "blue", "pieces": per},
        {"size": "M", "color": "blue", "pieces": per},
        {"size": "L", "color": "red", "pieces": per},
        {"size": "XL", "color": "red", "pieces": total - 3 * per},
    ]


def add_required_photos(db: Session, lot: Lot, owner: User, *, offset: int = 0) -> None:
    """The three photographs the readiness check requires.

    `offset` keeps the bytes distinct between lots, because the duplicate
    check is per lot and two lots built in one test would otherwise collide
    on the first image.
    """
    for index, kind in enumerate((PhotoKind.FULL_LOT, PhotoKind.FRONT, PhotoKind.LABEL), 1):
        catalog_service.add_photo(
            db,
            lot=lot,
            actor=owner,
            data=jpeg_bytes(seed=offset + index),
            content_type="image/jpeg",
            kind=kind,
        )


def ready_lot(db: Session, lot: Lot, owner: User, *, offset: int = 0) -> Lot:
    """A lot that passes every readiness check."""
    catalog_service.set_manifest(db, lot=lot, actor=owner, lines=balanced_manifest())
    add_required_photos(db, lot, owner, offset=offset)
    db.commit()
    return lot


def make_live(db: Session, lot: Lot) -> Lot:
    """Force a lot live, bypassing the state machine.

    Only for tests about behaviour while a lot is live. `approved_at` has to
    be set alongside the status, because the table has a CHECK constraint
    refusing a live lot that has never been approved, and SQLite enforces it.
    """
    lot.status = LotStatus.LIVE
    lot.approved_at = datetime.now(UTC)
    db.commit()
    return lot


def build_submitted_lot(
    db: Session,
    brand: Brand,
    owner: User,
    category_id: str,
    *,
    offset: int = 0,
    **overrides: object,
) -> Lot:
    """A lot that has passed readiness and is awaiting a decision."""
    lot = catalog_service.create_lot(
        db,
        brand_id=brand.id,
        actor=owner,
        data={**BASE_LOT, "category_id": category_id, **overrides},
    )
    ready_lot(db, lot, owner, offset=offset)
    approval_service.submit(db, lot=lot, actor=owner)
    db.commit()
    return lot
