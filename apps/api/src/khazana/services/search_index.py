"""Keep the search vectors current when a lot goes live.

Separate from `search_service` because the approval code calls it, and search
itself depends on the approval code's visibility rules.
"""

from __future__ import annotations

import logging

from sqlalchemy.orm import Session

from ..ai import embeddings
from ..models import Category, Lot
from ..models.enums import Visibility
from ..storage import read_object

logger = logging.getLogger(__name__)


def index_live_lot(db: Session, lot: Lot) -> None:
    """Index a lot's text, and its photographs unless it is unbranded.

    A search index problem must never stop a brand going live, so failures are
    logged and rolled back to a savepoint. Originals of an unbranded lot stay
    out of the index, because an image search would otherwise connect a brand's
    logo to the stock it chose to sell anonymously.
    """
    try:
        with db.begin_nested():
            category = db.get(Category, lot.category_id)
            embeddings.index_lot(db, lot, category_name=category.name if category else None)
            if Visibility(lot.visibility) == Visibility.UNBRANDED:
                return
            for photo in lot.photos:
                embeddings.index_photo(
                    db, photo_id=photo.id, lot=lot, data=read_object(photo.file_key)
                )
    except Exception as exc:
        logger.warning("could not index lot %s for search: %s", lot.id, exc)
