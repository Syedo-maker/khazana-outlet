"""The buyer assistant as a conversation, on the web and on WhatsApp."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from fastapi import APIRouter, Header, Request
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select

from ...config import get_settings
from ...core.tenancy import assert_owns
from ...models import AssistantConversation, AssistantMessage, WhatsAppMessage
from ...models.enums import ChatChannel, ChatRole, MessageDirection
from ...services import chat_service, whatsapp_providers, whatsapp_service
from ...services.whatsapp_providers import VoiceNote
from ..deps import AdminOnly, CurrentBrand, CurrentPrincipal, Db

router = APIRouter(tags=["assistant"])


class MessageOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    role: ChatRole
    body: str
    language: str | None
    lot_codes: list[str] = Field(default_factory=list)
    grounded: bool | None
    declined: bool | None
    created_at: datetime


class ConversationOut(BaseModel):
    id: str
    channel: ChatChannel
    title: str
    last_message_at: datetime | None


class ConversationDetailOut(ConversationOut):
    messages: list[MessageOut]


class UsageOut(BaseModel):
    limit: int
    used: int
    remaining: int


class SendIn(BaseModel):
    message: str = Field(min_length=1, max_length=2_000)
    conversation_id: str | None = Field(default=None, max_length=36)
    city: str = Field(default="", max_length=80)


class SendOut(BaseModel):
    conversation: ConversationOut
    buyer_message: MessageOut
    reply: MessageOut
    usage: UsageOut
    cost_usd: Decimal


def message_out(message: AssistantMessage) -> MessageOut:
    lots = message.tools_used.get("lots") if message.tools_used else None
    return MessageOut(
        id=message.id,
        role=message.role,
        body=message.body,
        language=message.language,
        lot_codes=[str(code) for code in lots] if isinstance(lots, list) else [],
        grounded=message.grounded,
        declined=message.declined,
        created_at=message.created_at,
    )


def conversation_out(conversation: AssistantConversation) -> ConversationOut:
    return ConversationOut(
        id=conversation.id,
        channel=conversation.channel,
        title=conversation.title,
        last_message_at=conversation.last_message_at,
    )


def _usage(db: Db, user_id: str) -> UsageOut:
    limit = get_settings().assistant_daily_message_limit
    used = chat_service.messages_sent_today(db, user_id)
    return UsageOut(limit=limit, used=used, remaining=max(0, limit - used))


@router.get(
    "/assistant/conversations",
    operation_id="assistant_list_conversations",
    response_model=list[ConversationOut],
)
def list_conversations(principal: CurrentPrincipal, db: Db) -> list[ConversationOut]:
    """The caller's own conversations, most recent first."""
    return [conversation_out(c) for c in chat_service.list_conversations(db, principal.user_id)]


@router.get(
    "/assistant/conversations/{conversation_id}",
    operation_id="assistant_conversation_detail",
    response_model=ConversationDetailOut,
    responses={404: {"description": "No such conversation for this account"}},
)
def get_conversation(
    conversation_id: str, principal: CurrentPrincipal, db: Db
) -> ConversationDetailOut:
    conversation = chat_service.get_conversation(db, principal.user_id, conversation_id)
    return ConversationDetailOut(
        **conversation_out(conversation).model_dump(),
        messages=[message_out(m) for m in conversation.messages],
    )


@router.get("/assistant/usage", operation_id="assistant_usage", response_model=UsageOut)
def usage(principal: CurrentPrincipal, db: Db) -> UsageOut:
    """How many assistant messages the caller has left today."""
    return _usage(db, principal.user_id)


@router.post(
    "/assistant/messages",
    operation_id="assistant_send_message",
    response_model=SendOut,
    responses={
        402: {"description": "An AI spend cap was reached before the call was made"},
        404: {"description": "No such conversation for this account"},
        429: {"description": "The daily message limit for this account was reached"},
    },
)
def send_message(payload: SendIn, principal: CurrentPrincipal, db: Db) -> SendOut:
    """Send a message and get the assistant's reply, in a new or existing thread."""
    exchange = chat_service.send(
        db,
        user_id=principal.user_id,
        text=payload.message,
        conversation_id=payload.conversation_id,
        city=payload.city,
    )
    db.commit()
    return SendOut(
        conversation=conversation_out(exchange.conversation),
        buyer_message=message_out(exchange.buyer_message),
        reply=message_out(exchange.reply),
        usage=_usage(db, principal.user_id),
        cost_usd=exchange.reply.cost_usd,
    )


# ---------- Brand assistant ----------


class BrandSendIn(BaseModel):
    message: str = Field(min_length=1, max_length=2_000)
    conversation_id: str | None = Field(default=None, max_length=36)


@router.get(
    "/brands/{brand_id}/assistant/conversations",
    operation_id="brand_assistant_conversations",
    response_model=list[ConversationOut],
    responses={404: {"description": "No such brand, or it belongs to someone else"}},
)
def brand_conversations(brand_id: str, principal: CurrentBrand, db: Db) -> list[ConversationOut]:
    """The caller's own threads with the assistant about this brand."""
    assert_owns(principal, brand_id)
    return [
        conversation_out(c)
        for c in chat_service.list_conversations(db, principal.user_id, brand_id=brand_id)
    ]


@router.get(
    "/brands/{brand_id}/assistant/conversations/{conversation_id}",
    operation_id="brand_assistant_conversation_detail",
    response_model=ConversationDetailOut,
    responses={404: {"description": "No such conversation for this account and brand"}},
)
def brand_conversation(
    brand_id: str, conversation_id: str, principal: CurrentBrand, db: Db
) -> ConversationDetailOut:
    assert_owns(principal, brand_id)
    conversation = chat_service.get_conversation(
        db, principal.user_id, conversation_id, brand_id=brand_id
    )
    return ConversationDetailOut(
        **conversation_out(conversation).model_dump(),
        messages=[message_out(m) for m in conversation.messages],
    )


@router.post(
    "/brands/{brand_id}/assistant/messages",
    operation_id="brand_assistant_send_message",
    response_model=SendOut,
    responses={
        402: {"description": "An AI spend cap was reached before the call was made"},
        404: {"description": "No such brand or conversation for this account"},
        429: {"description": "The daily message limit for this account was reached"},
    },
)
def brand_send_message(
    brand_id: str, payload: BrandSendIn, principal: CurrentBrand, db: Db
) -> SendOut:
    """Ask about this brand's own stock and sales.

    Every lookup is restricted to this brand by code. The assistant suggests
    and never changes a price.
    """
    assert_owns(principal, brand_id)
    exchange = chat_service.send(
        db,
        user_id=principal.user_id,
        text=payload.message,
        conversation_id=payload.conversation_id,
        brand_id=brand_id,
    )
    db.commit()
    return SendOut(
        conversation=conversation_out(exchange.conversation),
        buyer_message=message_out(exchange.buyer_message),
        reply=message_out(exchange.reply),
        usage=_usage(db, principal.user_id),
        cost_usd=exchange.reply.cost_usd,
    )


# ---------- WhatsApp ----------


class InboundOut(BaseModel):
    status: str
    duplicate: bool


@router.post(
    "/whatsapp/webhooks/{provider}",
    operation_id="whatsapp_inbound",
    response_model=InboundOut,
    responses={401: {"description": "The signature is missing or wrong"}},
)
async def whatsapp_inbound(
    provider: str,
    request: Request,
    db: Db,
    x_sandbox_signature: str | None = Header(default=None),
) -> InboundOut:
    """Receive one WhatsApp message. The signature is the authentication.

    A repeated delivery is accepted and not answered twice.
    """
    body = await request.body()

    def handle() -> whatsapp_service.InboundResult:
        result = whatsapp_service.ingest(db, provider, body, x_sandbox_signature)
        db.commit()
        return result

    # The reply makes two model calls, which must not hold the event loop.
    result = await run_in_threadpool(handle)
    return InboundOut(status=result.status, duplicate=result.duplicate)


class SandboxInboundIn(BaseModel):
    phone: str = Field(min_length=10, max_length=20)
    text: str = Field(default="", max_length=2_000)
    voice_transcript: str | None = Field(default=None, max_length=2_000)
    voice_confidence: float | None = Field(default=None, ge=0, le=1)
    voice_language: str | None = Field(default=None, max_length=8)


class SandboxInboundOut(BaseModel):
    status: str
    reply: str | None


@router.post(
    "/admin/whatsapp/sandbox/inbound",
    operation_id="admin_whatsapp_sandbox_inbound",
    response_model=SandboxInboundOut,
)
def sandbox_inbound(payload: SandboxInboundIn, _: AdminOnly, db: Db) -> SandboxInboundOut:
    """Pretend to be a buyer messaging the WhatsApp number, for testing.

    A voice transcript makes the message a voice note, with the given
    confidence standing in for what a speech model would report.
    """
    sandbox = whatsapp_providers.sandbox()
    voice = None
    if payload.voice_transcript is not None:
        voice = VoiceNote(
            media_id="sandbox-voice",
            duration_seconds=5,
            sandbox_transcript=payload.voice_transcript,
            sandbox_confidence=payload.voice_confidence,
            sandbox_language=payload.voice_language,
        )
    body, signature = sandbox.build_inbound(phone=payload.phone, text=payload.text, voice=voice)
    result = whatsapp_service.ingest(db, sandbox.name, body, signature)
    db.commit()
    return SandboxInboundOut(status=result.status, reply=result.reply)


class WhatsAppLogOut(BaseModel):
    id: str
    direction: MessageDirection
    phone: str
    body: str
    status: str
    transcript_confidence: float | None
    transcript_language: str | None
    created_at: datetime


@router.get(
    "/admin/whatsapp/messages",
    operation_id="admin_whatsapp_messages",
    response_model=list[WhatsAppLogOut],
)
def whatsapp_log(_: AdminOnly, db: Db) -> list[WhatsAppLogOut]:
    """The most recent WhatsApp traffic, both directions."""
    rows = db.scalars(
        select(WhatsAppMessage).order_by(WhatsAppMessage.created_at.desc()).limit(100)
    )
    return [
        WhatsAppLogOut(
            id=row.id,
            direction=row.direction,
            phone=row.phone,
            body=row.body,
            status=row.status,
            transcript_confidence=row.transcript_confidence,
            transcript_language=row.transcript_language,
            created_at=row.created_at,
        )
        for row in rows
    ]
