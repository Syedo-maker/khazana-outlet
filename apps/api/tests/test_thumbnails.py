"""Catalogue cards get a small copy of the cover photo.

Week 52's performance pass found every card downloading the full 1024 pixel
photograph. ``size=thumb`` serves a 400 pixel copy, made once and kept beside
the original, and removed with it.
"""

from __future__ import annotations

import io

from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy.orm import Session

from commerce_helpers import auth, live_lot, make_courier, make_reseller
from khazana.ai import images
from khazana.storage import get_backend, read_object, thumbnail_key


def test_a_card_gets_a_small_copy_made_once(
    client: TestClient, db: Session, two_brands, category
) -> None:  # type: ignore[no-untyped-def]
    (brand, owner), _ = two_brands
    make_courier(db)
    lot = live_lot(db, brand, owner, category.id)
    photo = lot.photos[0]
    buyer = make_reseller(db)
    url = f"/catalog/{lot.id}/photos/{photo.id}"

    full = client.get(url, headers=auth(buyer))
    thumb = client.get(f"{url}?size=thumb", headers=auth(buyer))
    assert full.status_code == thumb.status_code == 200
    small = Image.open(io.BytesIO(thumb.content))
    assert max(small.size) <= images.THUMB_EDGE_PX
    assert len(thumb.content) < len(full.content)

    key = photo.blurred_file_key or photo.file_key
    stored = read_object(thumbnail_key(key))
    assert stored == thumb.content, "kept, so the next card is not resized again"
    again = client.get(f"{url}?size=thumb", headers=auth(buyer))
    assert again.content == stored


def test_deleting_a_photo_deletes_its_thumbnail(db: Session) -> None:
    from khazana.storage import delete_object, put_object

    key = "photos/brand/abc.jpg"
    put_object(key, b"\xff\xd8\xff" + b"0" * 100, "image/jpeg")
    put_object(thumbnail_key(key), b"\xff\xd8\xff" + b"1" * 10, "image/jpeg")
    delete_object(key)
    backend = get_backend()
    assert not backend.exists(key)
    assert not backend.exists(thumbnail_key(key))
