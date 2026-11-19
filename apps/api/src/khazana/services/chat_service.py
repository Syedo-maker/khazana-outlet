"""Conversations with the buyer assistant.

The assistant feature answers one message. This service turns that into a
conversation: it keeps the thread, passes the last few messages back as
context, and caps how many messages one account can send in a day.

Three rules, each enforced here rather than trusted to a caller:

- A conversation belongs to one user. Anyone else asking for it gets a 404,
  the same answer as for a conversation that does not exist.
- The cap is counted per account per Pakistan day, before any model call, so
  a refused message costs nothing.
- Messages are written only after a reply exists. A failed model call leaves
  no buyer message without an answer, and does not count against the cap.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..ai.features import assistant
from ..ai.features.assistant import AssistantTurn
from ..config import get_settings
from ..core.errors import NotFound, RateLimited, ValidationFailed
from ..models import AssistantConversation, AssistantMessage, utcnow
from ..models.enums import ChatChannel, ChatRole

# Pakistan Standard Time. Fixed, because Pakistan has not observed daylight
# saving since 2009, and a fixed offset needs no tz database on Windows.
PAKISTAN_TIME = timezone(timedelta(hours=5), "PKT")
TITLE_CHARS = 80
# Each earlier message is cut to this length before it goes back to the model,
# so one long paste cannot make every later turn expensive.
HISTORY_MESSAGE_CHARS = 500


@dataclass(slots=True)
class ChatExchange:
    conversation: AssistantConversation
    buyer_message: AssistantMessage
    reply: AssistantMessage
    turn: AssistantTurn


def start_of_pakistan_day(now: datetime) -> datetime:
    """Midnight in Pakistan for the day containing ``now``, in UTC."""
    local = now.astimezone(PAKISTAN_TIME)
    midnight = local.replace(hour=0, minute=0, second=0, microsecond=0)
    return midnight.astimezone(UTC)


def messages_sent_today(db: Session, user_id: str, now: datetime | None = None) -> int:
    since = start_of_pakistan_day(now or utcnow())
    count = db.scalar(
        select(func.count())
        .select_from(AssistantMessage)
        .where(
            AssistantMessage.user_id == user_id,
            AssistantMessage.role == ChatRole.BUYER,
            AssistantMessage.created_at >= since,
        )
    )
    return int(count or 0)


def remaining_today(db: Session, user_id: str, now: datetime | None = None) -> int:
    limit = get_settings().assistant_daily_message_limit
    return max(0, limit - messages_sent_today(db, user_id, now))


def list_conversations(db: Session, user_id: str, limit: int = 30) -> list[AssistantConversation]:
    return list(
        db.scalars(
            select(AssistantConversation)
            .where(AssistantConversation.user_id == user_id)
            .order_by(
                AssistantConversation.last_message_at.desc(),
                AssistantConversation.created_at.desc(),
            )
            .limit(limit)
        )
    )


def get_conversation(db: Session, user_id: str, conversation_id: str) -> AssistantConversation:
    conversation = db.get(AssistantConversation, conversation_id)
    if conversation is None or conversation.user_id != user_id:
        raise NotFound("That conversation does not exist.")
    return conversation


def latest_conversation(
    db: Session, user_id: str, channel: ChatChannel
) -> AssistantConversation | None:
    return db.scalar(
        select(AssistantConversation)
        .where(AssistantConversation.user_id == user_id, AssistantConversation.channel == channel)
        .order_by(AssistantConversation.last_message_at.desc())
        .limit(1)
    )


def recent_messages(db: Session, conversation_id: str, limit: int) -> list[AssistantMessage]:
    """The last ``limit`` messages of a thread, oldest first.

    Read with a query rather than through the relationship, because a loaded
    relationship does not see messages added later in the same session.
    """
    if limit <= 0:
        return []
    newest_first = db.scalars(
        select(AssistantMessage)
        .where(AssistantMessage.conversation_id == conversation_id)
        .order_by(AssistantMessage.created_at.desc())
        .limit(limit)
    )
    return list(reversed(list(newest_first)))


def render_history(messages: list[AssistantMessage]) -> str:
    """Messages as plain labelled lines, in the order given."""
    lines = []
    for message in messages:
        speaker = "Buyer" if message.role == ChatRole.BUYER else "Assistant"
        text = " ".join(message.body.split())
        if len(text) > HISTORY_MESSAGE_CHARS:
            text = text[:HISTORY_MESSAGE_CHARS].rstrip() + "..."
        lines.append(f"{speaker}: {text}")
    return "\n".join(lines)


def _title(text: str) -> str:
    flat = " ".join(text.split())
    if len(flat) <= TITLE_CHARS:
        return flat
    return flat[: TITLE_CHARS - 3].rstrip() + "..."


def send(
    db: Session,
    *,
    user_id: str,
    text: str,
    conversation_id: str | None = None,
    channel: ChatChannel = ChatChannel.WEB,
    city: str = "",
    conversation: AssistantConversation | None = None,
) -> ChatExchange:
    """Send one buyer message and store it with the assistant's reply.

    The caller commits. The model calls inside commit their own cost records,
    which is why nothing is added to the session until the reply is back.
    """
    if not text.strip():
        raise ValidationFailed("Type a message first.")

    if conversation is None and conversation_id is not None:
        conversation = get_conversation(db, user_id, conversation_id)
    if conversation is not None and conversation.user_id != user_id:
        raise NotFound("That conversation does not exist.")

    limit = get_settings().assistant_daily_message_limit
    if messages_sent_today(db, user_id) >= limit:
        raise RateLimited(
            f"You have sent {limit} messages to the assistant today. "
            "The limit resets at midnight Pakistan time."
        )

    history = ""
    if conversation is not None:
        keep = get_settings().assistant_history_messages
        history = render_history(recent_messages(db, conversation.id, keep))
    turn = assistant.ask(db, message=text, buyer_user_id=user_id, buyer_city=city, history=history)

    if conversation is None:
        conversation = AssistantConversation(user_id=user_id, channel=channel, title=_title(text))
        db.add(conversation)
        db.flush()

    sent_at = utcnow()
    # A reply written within the same clock tick as the question would sort
    # ambiguously, so it is always at least a microsecond later.
    replied_at = max(utcnow(), sent_at + timedelta(microseconds=1))
    buyer_message = AssistantMessage(
        conversation_id=conversation.id,
        user_id=user_id,
        role=ChatRole.BUYER,
        body=text.strip(),
        language=turn.plan.language,
        tools_used={},
        cost_usd=Decimal(0),
        created_at=sent_at,
        updated_at=sent_at,
    )
    reply = AssistantMessage(
        conversation_id=conversation.id,
        user_id=user_id,
        role=ChatRole.ASSISTANT,
        body=turn.answer.answer,
        language=turn.answer.language,
        tools_used={
            "tools": list(turn.answer.tool_calls_made),
            "lots": list(turn.answer.lot_ids_referenced),
        },
        grounded=turn.is_grounded,
        declined=turn.answer.declined,
        cost_usd=Decimal(str(turn.total_cost_usd)),
        created_at=replied_at,
        updated_at=replied_at,
    )
    db.add_all([buyer_message, reply])
    conversation.last_message_at = replied_at
    db.flush()
    return ChatExchange(
        conversation=conversation, buyer_message=buyer_message, reply=reply, turn=turn
    )
