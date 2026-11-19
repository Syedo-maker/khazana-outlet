"""Conversations with the buyer assistant, on the web and on WhatsApp.

A conversation belongs to one user and is never shared. Nothing here carries
a brand_id: the buyer assistant answers from the public catalogue, and what a
buyer asked is the buyer's data, not a brand's.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base, TimestampMixin, UUIDPrimaryKey
from .enums import ChatChannel, ChatRole, MessageDirection


class AssistantConversation(UUIDPrimaryKey, TimestampMixin, Base):
    """One thread of messages between a user and the assistant."""

    __tablename__ = "assistant_conversations"

    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    channel: Mapped[ChatChannel] = mapped_column(nullable=False, default=ChatChannel.WEB)
    # The first buyer message, shortened. Written by code, never by the model.
    title: Mapped[str] = mapped_column(String(120), nullable=False, default="")
    last_message_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)

    messages: Mapped[list[AssistantMessage]] = relationship(
        back_populates="conversation",
        order_by="AssistantMessage.created_at",
        cascade="all, delete-orphan",
    )

    __table_args__ = (
        Index("ix_assistant_conversations_user_recent", "user_id", "last_message_at"),
    )


class AssistantMessage(UUIDPrimaryKey, TimestampMixin, Base):
    """One message in a conversation, from the buyer or from the assistant."""

    __tablename__ = "assistant_messages"

    conversation_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("assistant_conversations.id", ondelete="CASCADE"), nullable=False
    )
    # Denormalised so the daily cap is one indexed count, not a join.
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    role: Mapped[ChatRole] = mapped_column(nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    language: Mapped[str | None] = mapped_column(String(16), default=None)
    tools_used: Mapped[dict[str, object]] = mapped_column(nullable=False, default=dict)
    grounded: Mapped[bool | None] = mapped_column(Boolean, default=None)
    declined: Mapped[bool | None] = mapped_column(Boolean, default=None)
    cost_usd: Mapped[Decimal] = mapped_column(Numeric(10, 6), nullable=False, default=Decimal(0))

    conversation: Mapped[AssistantConversation] = relationship(back_populates="messages")

    __table_args__ = (
        Index("ix_assistant_messages_conversation_created", "conversation_id", "created_at"),
        Index("ix_assistant_messages_user_role_created", "user_id", "role", "created_at"),
    )


class WhatsAppMessage(UUIDPrimaryKey, TimestampMixin, Base):
    """Every message sent or received on WhatsApp, as the provider saw it.

    The provider message id is unique, so a webhook delivered twice is stored
    once and answered once.
    """

    __tablename__ = "whatsapp_messages"

    direction: Mapped[MessageDirection] = mapped_column(nullable=False)
    phone: Mapped[str] = mapped_column(String(20), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False, default="")
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    provider_message_id: Mapped[str] = mapped_column(String(120), nullable=False, unique=True)
    user_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="SET NULL"), default=None
    )
    conversation_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("assistant_conversations.id", ondelete="SET NULL"), default=None
    )
    # Voice notes: the stored audio key and the transcription, when there is one.
    media_key: Mapped[str | None] = mapped_column(String(300), default=None)
    transcript_confidence: Mapped[float | None] = mapped_column(default=None)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="received")
