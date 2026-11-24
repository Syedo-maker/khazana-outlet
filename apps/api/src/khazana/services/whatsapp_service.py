"""The buyer assistant on WhatsApp, including voice notes.

A webhook arrives, is verified and logged, and is answered through the same
chat service the web uses, so the cap, the history and the grounding rules
are identical on both channels.

Who gets a model call: only a registered account. A message from an unknown
number gets a fixed sign up reply and costs nothing, because a public number
that answers anyone with a paid model is a bill anyone can run up.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, timedelta

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..config import get_settings
from ..core.errors import AppError, RateLimited, ValidationFailed
from ..models import AssistantConversation, User, WhatsAppMessage, utcnow
from ..models.enums import ChatChannel, MessageDirection
from . import chat_service, whatsapp_providers
from .auth_service import normalise_phone
from .whatsapp_providers import InboundMessage, WhatsAppProvider

# Fixed replies, written by people. Each is English then Roman Urdu, because
# the sender's language is not known before the model reads the message.
SIGN_UP_REPLY = (
    "This number is not registered on Khazana Outlet yet. Sign up at {url} with "
    "this number, then message again.\n"
    "Yeh number abhi Khazana Outlet par register nahi hai. {url} par isi number se "
    "sign up karein, phir dobara message karein."
)
VOICE_UNCLEAR_REPLY = (
    "Sorry, I could not hear that voice note clearly. Please type your question.\n"
    "Maaf kijiye, voice note saaf samajh nahi aaya. Apna sawal likh kar bhejein."
)
UNAVAILABLE_REPLY = (
    "The assistant is not available right now. Please try again later.\n"
    "Assistant abhi dastiyab nahi hai. Thori dair baad dobara koshish karein."
)


@dataclass(slots=True)
class InboundResult:
    status: str
    duplicate: bool = False
    reply: str | None = None


def _log(
    db: Session,
    *,
    direction: MessageDirection,
    phone: str,
    body: str,
    provider: str,
    provider_message_id: str,
    status: str,
    user_id: str | None = None,
    conversation_id: str | None = None,
    media_key: str | None = None,
    confidence: float | None = None,
) -> WhatsAppMessage:
    record = WhatsAppMessage(
        direction=direction,
        phone=phone,
        body=body,
        provider=provider,
        provider_message_id=provider_message_id,
        status=status,
        user_id=user_id,
        conversation_id=conversation_id,
        media_key=media_key,
        transcript_confidence=confidence,
    )
    db.add(record)
    db.flush()
    return record


def _send(
    db: Session,
    provider: WhatsAppProvider,
    *,
    phone: str,
    text: str,
    user_id: str | None,
    conversation_id: str | None = None,
) -> None:
    message_id = provider.send_text(phone, text)
    _log(
        db,
        direction=MessageDirection.OUTBOUND,
        phone=phone,
        body=text,
        provider=provider.name,
        provider_message_id=message_id,
        status="sent",
        user_id=user_id,
        conversation_id=conversation_id,
    )


def _conversation_for(db: Session, user_id: str) -> AssistantConversation | None:
    """The current WhatsApp thread, or None when the next message starts one."""
    latest = chat_service.latest_conversation(db, user_id, ChatChannel.WHATSAPP)
    if latest is None or latest.last_message_at is None:
        return None
    last = latest.last_message_at
    if last.tzinfo is None:
        last = last.replace(tzinfo=UTC)
    idle = timedelta(hours=get_settings().whatsapp_conversation_idle_hours)
    if utcnow() - last > idle:
        return None
    return latest


def ingest(db: Session, provider_name: str, body: bytes, signature: str | None) -> InboundResult:
    """Verify, log and answer one inbound WhatsApp message. The caller commits."""
    provider = whatsapp_providers.provider_for(provider_name)
    inbound = provider.parse_inbound(body, signature)

    if db.scalar(
        select(WhatsAppMessage.id).where(WhatsAppMessage.provider_message_id == inbound.message_id)
    ):
        return InboundResult(status="duplicate", duplicate=True)

    return _answer(db, provider, inbound)


def _answer(db: Session, provider: WhatsAppProvider, inbound: InboundMessage) -> InboundResult:
    settings = get_settings()
    try:
        phone = normalise_phone(inbound.phone)
    except ValidationFailed:
        _log(
            db,
            direction=MessageDirection.INBOUND,
            phone=inbound.phone[:20],
            body=inbound.text,
            provider=provider.name,
            provider_message_id=inbound.message_id,
            status="ignored_number",
        )
        return InboundResult(status="ignored_number")

    user = db.scalar(select(User).where(User.phone == phone))
    try:
        record = _log(
            db,
            direction=MessageDirection.INBOUND,
            phone=phone,
            body=inbound.text,
            provider=provider.name,
            provider_message_id=inbound.message_id,
            status="received",
            user_id=user.id if user else None,
            media_key=inbound.voice.media_id if inbound.voice else None,
        )
    except IntegrityError:
        # The same message delivered twice at once. The other delivery won.
        db.rollback()
        return InboundResult(status="duplicate", duplicate=True)

    if user is None:
        reply = SIGN_UP_REPLY.format(url=settings.web_base_url)
        record.status = "unknown_sender"
        _send(db, provider, phone=phone, text=reply, user_id=None)
        return InboundResult(status=record.status, reply=reply)

    text = inbound.text
    if inbound.voice is not None:
        # Transcription is paid for too, so a buyer at the daily limit is told
        # so before the voice note is sent to the speech service.
        if chat_service.remaining_today(db, user.id) == 0:
            limit = settings.assistant_daily_message_limit
            message = (
                f"You have sent {limit} messages to the assistant today. "
                "The limit resets at midnight Pakistan time."
            )
            record.status = "rate_limited"
            _send(db, provider, phone=phone, text=message, user_id=user.id)
            return InboundResult(status=record.status, reply=message)
        problem = _voice_problem(inbound.voice)
        if problem is not None:
            record.status = "voice_refused"
            _send(db, provider, phone=phone, text=problem, user_id=user.id)
            return InboundResult(status=record.status, reply=problem)
        transcript = whatsapp_providers.transcriber().transcribe(inbound.voice)
        record.transcript_confidence = transcript.confidence
        record.transcript_language = transcript.language
        if not transcript.text.strip() or transcript.confidence < settings.voice_min_confidence:
            record.status = "voice_unclear"
            _send(db, provider, phone=phone, text=VOICE_UNCLEAR_REPLY, user_id=user.id)
            return InboundResult(status=record.status, reply=VOICE_UNCLEAR_REPLY)
        record.body = transcript.text
        text = transcript.text

    conversation = _conversation_for(db, user.id)
    try:
        exchange = chat_service.send(
            db,
            user_id=user.id,
            text=text,
            channel=ChatChannel.WHATSAPP,
            city=user.reseller_profile.city if user.reseller_profile else "",
            conversation=conversation,
        )
    except RateLimited as exc:
        record.status = "rate_limited"
        _send(db, provider, phone=phone, text=exc.message, user_id=user.id)
        return InboundResult(status=record.status, reply=exc.message)
    except AppError:
        record.status = "assistant_unavailable"
        _send(db, provider, phone=phone, text=UNAVAILABLE_REPLY, user_id=user.id)
        return InboundResult(status=record.status, reply=UNAVAILABLE_REPLY)

    record.status = "answered"
    record.conversation_id = exchange.conversation.id
    _send(
        db,
        provider,
        phone=phone,
        text=exchange.reply.body,
        user_id=user.id,
        conversation_id=exchange.conversation.id,
    )
    return InboundResult(status=record.status, reply=exchange.reply.body)


def _voice_problem(voice: whatsapp_providers.VoiceNote) -> str | None:
    """Why a voice note will not be transcribed, or None when it will.

    Transcription is billed by the minute, so a long recording is refused
    before it reaches the speech service, not after.
    """
    limit = get_settings().voice_max_seconds
    if voice.mime_type not in whatsapp_providers.VOICE_MIME_TYPES:
        return (
            "Sorry, I can only listen to WhatsApp voice notes. Please type your question.\n"
            "Maaf kijiye, sirf WhatsApp voice note sun sakta hoon. Apna sawal likh kar bhejein."
        )
    if voice.duration_seconds <= 0 or voice.duration_seconds > limit:
        return (
            f"Please keep voice notes under {limit // 60} minutes, or type your question.\n"
            f"Voice note {limit // 60} minute se chhota rakhein, ya sawal likh kar bhejein."
        )
    return None
