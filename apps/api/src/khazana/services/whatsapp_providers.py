"""The boundary between the marketplace and WhatsApp.

Only a sandbox exists. The WhatsApp Business Platform needs a verified business,
an approved phone number and approved message templates, none of which exist
before the company does. The sandbox has the same shape a real adapter will
have: signed inbound webhooks, idempotent message ids and an outbound send.

Voice notes go through a separate transcriber, because Claude does not take
audio. The sandbox transcriber reads a transcript the test sender supplied, with
a confidence, so the low confidence path can be exercised without a speech
model. A real one will implement ``Transcriber`` when a speech service is chosen.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import uuid
from dataclasses import dataclass, field
from typing import Any, Protocol

from ..config import get_settings
from ..core.errors import Conflict, Unauthenticated, ValidationFailed

SIGNATURE_HEADER = "x-sandbox-signature"
MAX_TEXT_CHARS = 2_000


@dataclass(frozen=True, slots=True)
class VoiceNote:
    """Audio the buyer recorded. ``sandbox_transcript`` exists only in the sandbox."""

    media_id: str
    duration_seconds: int
    sandbox_transcript: str | None = None
    sandbox_confidence: float | None = None


@dataclass(frozen=True, slots=True)
class InboundMessage:
    message_id: str
    phone: str
    text: str
    voice: VoiceNote | None = None
    payload: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class Transcript:
    text: str
    confidence: float


class WhatsAppProvider(Protocol):
    name: str

    def parse_inbound(self, body: bytes, signature: str | None) -> InboundMessage: ...
    def send_text(self, phone: str, text: str) -> str: ...


class Transcriber(Protocol):
    def transcribe(self, voice: VoiceNote) -> Transcript: ...


class SandboxWhatsAppProvider:
    """Stands in for the WhatsApp Business Platform, with signed webhooks.

    Sent messages are kept in ``outbox`` so tests and the admin sandbox can see
    exactly what a buyer would have received.
    """

    name = "sandbox"

    def __init__(self) -> None:
        self.outbox: list[tuple[str, str, str]] = []

    def _key(self) -> bytes:
        return f"{get_settings().secret_key}:whatsapp:{self.name}".encode()

    def sign(self, body: bytes) -> str:
        return hmac.new(self._key(), body, hashlib.sha256).hexdigest()

    def build_inbound(
        self,
        *,
        phone: str,
        text: str = "",
        voice: VoiceNote | None = None,
        message_id: str | None = None,
    ) -> tuple[bytes, str]:
        payload: dict[str, Any] = {
            "message_id": message_id or f"wamid.{uuid.uuid4().hex}",
            "from": phone,
            "text": text,
        }
        if voice is not None:
            payload["voice"] = {
                "media_id": voice.media_id,
                "duration_seconds": voice.duration_seconds,
                "sandbox_transcript": voice.sandbox_transcript,
                "sandbox_confidence": voice.sandbox_confidence,
            }
        body = json.dumps(payload, sort_keys=True).encode()
        return body, self.sign(body)

    def parse_inbound(self, body: bytes, signature: str | None) -> InboundMessage:
        # The signature is checked on the raw bytes, before anything is parsed.
        if not signature or not hmac.compare_digest(self.sign(body), signature):
            raise Unauthenticated("The WhatsApp webhook signature is not valid.")
        try:
            payload = json.loads(body)
            voice_raw = payload.get("voice")
            voice = None
            if voice_raw:
                confidence = voice_raw.get("sandbox_confidence")
                voice = VoiceNote(
                    media_id=str(voice_raw["media_id"]),
                    duration_seconds=int(voice_raw.get("duration_seconds") or 0),
                    sandbox_transcript=voice_raw.get("sandbox_transcript"),
                    sandbox_confidence=None if confidence is None else float(confidence),
                )
            text = str(payload.get("text") or "")[:MAX_TEXT_CHARS]
            if not text.strip() and voice is None:
                raise ValueError("empty message")
            return InboundMessage(
                message_id=str(payload["message_id"]),
                phone=str(payload["from"]),
                text=text,
                voice=voice,
                payload=payload,
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise ValidationFailed("The WhatsApp webhook body is not valid.") from exc

    def send_text(self, phone: str, text: str) -> str:
        message_id = f"wamid.out.{uuid.uuid4().hex}"
        self.outbox.append((message_id, phone, text))
        return message_id


class SandboxTranscriber:
    """Returns the transcript the sandbox sender attached, or nothing."""

    def transcribe(self, voice: VoiceNote) -> Transcript:
        if not voice.sandbox_transcript:
            return Transcript(text="", confidence=0.0)
        confidence = voice.sandbox_confidence
        return Transcript(
            text=voice.sandbox_transcript,
            confidence=0.0 if confidence is None else max(0.0, min(1.0, confidence)),
        )


_SANDBOX = SandboxWhatsAppProvider()
_TRANSCRIBER = SandboxTranscriber()


def provider_for(name: str) -> WhatsAppProvider:
    if name != _SANDBOX.name:
        raise Conflict("That WhatsApp provider is not available.")
    if get_settings().is_production:
        raise Conflict("The WhatsApp sandbox is not available in production.")
    return _SANDBOX


def sandbox() -> SandboxWhatsAppProvider:
    return _SANDBOX


def transcriber() -> Transcriber:
    return _TRANSCRIBER
