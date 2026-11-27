"""Uploads are bounded before they cost memory, and photos lose what they should.

From week 51's security pass:

- Every upload route read the whole file into memory before the size check.
- A small PNG declaring enormous dimensions was decoded in full, a
  decompression bomb, or crashed the request with a 500.
- Re-encoding already stripped EXIF, including a warehouse's GPS position,
  but discarded the camera's orientation with it, so phone photos could end
  up on their side.
- Voice notes had no length limit before paid transcription.
"""

from __future__ import annotations

import io

import pytest
from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy.orm import Session

from catalog_helpers import build_submitted_lot, jpeg_bytes
from commerce_helpers import auth, make_reseller
from khazana.ai import images
from khazana.services import whatsapp_providers, whatsapp_service
from khazana.services.whatsapp_providers import VoiceNote
from khazana.storage import MAX_UPLOAD_BYTES

# WhatsApp and voice notes are off by default for the pilot; these tests
# exercise the sandbox providers behind those switches.
pytestmark = pytest.mark.usefixtures("paid_providers_on")


def test_an_oversized_upload_is_refused_with_413(
    client: TestClient, db: Session, two_brands, category
) -> None:  # type: ignore[no-untyped-def]
    (brand, owner), _ = two_brands
    lot = build_submitted_lot(db, brand, owner, category.id)
    big = jpeg_bytes(width=16, height=16) + b"\0" * (MAX_UPLOAD_BYTES + 1)
    response = client.post(
        f"/lots/{lot.id}/photos",
        headers=auth(owner),
        files={"file": ("big.jpg", big, "image/jpeg")},
        data={"kind": "front"},
    )
    assert response.status_code == 413
    assert response.json()["detail"]["code"] == "too_large"


def test_a_decompression_bomb_is_refused_before_it_is_decoded() -> None:
    # Eight thousand pixels square of one colour: a few kilobytes as a PNG,
    # 64 megapixels once decoded.
    buffer = io.BytesIO()
    Image.new("1", (8_000, 8_000)).save(buffer, format="PNG")
    assert len(buffer.getvalue()) < 100_000
    with pytest.raises(images.ImageError, match="too large"):
        images.prepare(buffer.getvalue())


def _phone_photo() -> bytes:
    """A landscape sensor image the camera marked as rotated, with a GPS tag."""
    image = Image.new("RGB", (40, 20), "red")
    exif = Image.Exif()
    exif[0x0112] = 6  # orientation: rotate 90 degrees clockwise to view
    exif[0x8825] = {2: (31.0, 30.0, 0.0)}  # GPSInfo: a latitude
    buffer = io.BytesIO()
    image.save(buffer, format="JPEG", exif=exif)
    return buffer.getvalue()


def test_a_phone_photo_is_turned_upright_and_loses_its_location() -> None:
    prepared = images.prepare(_phone_photo())
    stored = Image.open(io.BytesIO(prepared.data))
    assert (stored.width, stored.height) == (20, 40), "the orientation was applied"
    exif = stored.getexif()
    assert 0x8825 not in exif, "no GPS position survives"
    assert 0x0112 not in exif, "no orientation flag left to apply twice"


class _Spy:
    def __init__(self) -> None:
        self.calls: list[object] = []

    def transcribe(self, voice: object) -> object:
        self.calls.append(voice)
        raise AssertionError("a refused voice note was sent for transcription")


@pytest.mark.parametrize(
    ("voice", "words"),
    [
        (VoiceNote(media_id="long", duration_seconds=900), "under 2 minutes"),
        (VoiceNote(media_id="empty", duration_seconds=0), "under 2 minutes"),
        (VoiceNote(media_id="doc", duration_seconds=5, mime_type="application/pdf"), "voice notes"),
    ],
)
def test_a_voice_note_is_checked_before_paid_transcription(
    db: Session, monkeypatch: pytest.MonkeyPatch, voice: VoiceNote, words: str
) -> None:
    make_reseller(db)
    spy = _Spy()
    monkeypatch.setattr(whatsapp_providers, "transcriber", lambda: spy)
    body, signature = whatsapp_providers.sandbox().build_inbound(phone="03007777777", voice=voice)
    result = whatsapp_service.ingest(db, "sandbox", body, signature)
    assert result.status == "voice_refused"
    assert words in (result.reply or "")
    assert spy.calls == []
