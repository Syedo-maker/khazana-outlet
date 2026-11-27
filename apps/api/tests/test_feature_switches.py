"""Features that need a paid provider are off for the pilot, and say so.

WhatsApp Business, speech to text and photo search each cost money per use
in production. With their switches off, nothing fails: the web app hides the
control and explains, the API answers with the same explanation, and a voice
note sent by WhatsApp is answered with a request to type.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from catalog_helpers import jpeg_bytes
from commerce_helpers import auth, make_reseller
from khazana.services import whatsapp_providers, whatsapp_service
from khazana.services.whatsapp_providers import VoiceNote


def test_photo_search_answers_with_an_explanation_not_an_error(
    client: TestClient, db: Session
) -> None:
    buyer = make_reseller(db)
    response = client.post(
        "/catalog/search/photo",
        files={"file": ("shirt.jpg", jpeg_bytes(), "image/jpeg")},
        headers=auth(buyer),
    )
    assert response.status_code == 200
    body = response.json()
    assert body["items"] == []
    assert body["method"] == "unavailable"
    assert "switched off" in body["note"]


def test_the_whatsapp_webhook_is_closed(client: TestClient) -> None:
    response = client.post("/whatsapp/webhooks/sandbox", content=b"{}")
    assert response.status_code == 503
    assert "WhatsApp" in response.json()["message"]


def test_the_admin_sandbox_says_whatsapp_is_off(client: TestClient, admin_user) -> None:  # type: ignore[no-untyped-def]
    response = client.post(
        "/admin/whatsapp/sandbox/inbound",
        json={"phone": "03007777777", "text": "salam"},
        headers=auth(admin_user),
    )
    assert response.status_code == 503
    assert "WHATSAPP_ENABLED" in response.json()["message"]


def test_a_voice_note_is_answered_with_a_request_to_type(
    db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    """WhatsApp on, speech to text off: the buyer is asked to type, in both
    languages, and the paid transcriber is never called."""
    from khazana.config import get_settings

    monkeypatch.setenv("WHATSAPP_ENABLED", "true")
    get_settings.cache_clear()
    make_reseller(db, phone="03007777777")

    called: list[object] = []

    class Counting:
        def transcribe(self, voice: object) -> object:
            called.append(voice)
            raise AssertionError("the transcriber must not be called")

    monkeypatch.setattr(whatsapp_providers, "transcriber", lambda: Counting())
    sandbox = whatsapp_providers.sandbox()
    body, signature = sandbox.build_inbound(
        phone="03007777777",
        text="",
        voice=VoiceNote(media_id="v1", duration_seconds=8, sandbox_transcript="salam"),
    )
    try:
        result = whatsapp_service.ingest(db, sandbox.name, body, signature)
    finally:
        get_settings.cache_clear()
    assert result.status == "voice_off"
    assert result.reply is not None
    assert "type" in result.reply
    assert "likh kar" in result.reply
    assert not called
