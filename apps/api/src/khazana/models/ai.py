"""AI jobs, outputs, the spend ledger and embeddings.

These four tables are what make the AI layer measurable instead of magical.

``AiOutput`` stores both what the model produced and what the human changed it
to. That pairing is the quality metric now and the training corpus later, and
it costs nothing to collect if the column exists from week 2 rather than being
added in year two when the data is already lost.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base, TimestampMixin, UUIDPrimaryKey, Vector
from .enums import AiFeature, AiJobStatus, AiMode, EmbeddingOwner


class AiJob(UUIDPrimaryKey, TimestampMixin, Base):
    """One unit of AI work, queued rather than run inside a web request.

    Every model call in the platform creates one of these, including the
    offline fixture runs in development, so the job table is a complete
    history of what the AI layer was asked to do.
    """

    __tablename__ = "ai_jobs"

    feature: Mapped[AiFeature] = mapped_column(String(32), nullable=False)
    status: Mapped[AiJobStatus] = mapped_column(
        String(24), nullable=False, default=AiJobStatus.QUEUED
    )
    mode: Mapped[AiMode] = mapped_column(String(10), nullable=False, default=AiMode.LIVE)

    # Loose coupling on purpose: a job can target a lot, a photo, an order or
    # nothing at all, and the AI layer must not need a foreign key per feature.
    entity_type: Mapped[str | None] = mapped_column(String(40), default=None)
    entity_id: Mapped[str | None] = mapped_column(String(36), default=None)

    brand_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("brands.id", ondelete="SET NULL"), default=None
    )
    requested_by_user_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="SET NULL"), default=None
    )

    # Set when a spend cap or a kill switch stopped the job. Keeping the row
    # rather than discarding it is what lets you see that a feature is being
    # throttled instead of quietly doing nothing.
    blocked_reason: Mapped[str | None] = mapped_column(String(255), default=None)

    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error: Mapped[str | None] = mapped_column(Text, default=None)

    outputs: Mapped[list[AiOutput]] = relationship(
        back_populates="job", cascade="all, delete-orphan"
    )

    __table_args__ = (
        Index("ix_ai_jobs_feature_status", "feature", "status"),
        Index("ix_ai_jobs_entity", "entity_type", "entity_id"),
        Index("ix_ai_jobs_brand_created", "brand_id", "created_at"),
    )


class AiOutput(UUIDPrimaryKey, TimestampMixin, Base):
    """What one model call produced, what it cost, and what the human changed.

    Token and cost fields are not optional extras. Without them you cannot
    answer the only two questions that matter about an AI feature in
    production: is it good, and what does it cost per use.
    """

    __tablename__ = "ai_outputs"

    job_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("ai_jobs.id", ondelete="CASCADE"), nullable=False
    )

    model: Mapped[str] = mapped_column(String(60), nullable=False)
    prompt_name: Mapped[str] = mapped_column(String(80), nullable=False)
    prompt_version: Mapped[int] = mapped_column(Integer, nullable=False)
    effort: Mapped[str | None] = mapped_column(String(10), default=None)

    input_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    cache_read_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    cache_write_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    cost_usd: Mapped[Decimal] = mapped_column(Numeric(10, 6), nullable=False, default=0)
    latency_ms: Mapped[int | None] = mapped_column(Integer, default=None)

    # The model's structured result, exactly as validated against the schema.
    output: Mapped[dict[str, object] | None] = mapped_column(default=None)
    # Filled in when a human accepts or edits the draft. The diff between
    # ``output`` and ``human_corrected`` is the quality signal.
    accepted: Mapped[bool | None] = mapped_column(Boolean, default=None)
    human_corrected: Mapped[dict[str, object] | None] = mapped_column(default=None)
    reviewed_by_user_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="SET NULL"), default=None
    )
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)

    job: Mapped[AiJob] = relationship(back_populates="outputs")

    __table_args__ = (
        CheckConstraint("input_tokens >= 0", name="input_tokens_non_negative"),
        CheckConstraint("output_tokens >= 0", name="output_tokens_non_negative"),
        CheckConstraint("cost_usd >= 0", name="cost_non_negative"),
        Index("ix_ai_outputs_prompt", "prompt_name", "prompt_version"),
        Index("ix_ai_outputs_accepted", "accepted"),
    )


class AiSpend(UUIDPrimaryKey, TimestampMixin, Base):
    """Daily spend per feature, and per brand where a brand caused it.

    Spend caps are enforced against this table before a call is made, not
    after the invoice arrives. A null ``brand_id`` is platform level spend,
    such as the buyer assistant.
    """

    __tablename__ = "ai_spend"

    day: Mapped[date] = mapped_column(Date, nullable=False)
    feature: Mapped[AiFeature] = mapped_column(String(32), nullable=False)
    brand_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("brands.id", ondelete="CASCADE"), default=None
    )
    calls: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    cost_usd: Mapped[Decimal] = mapped_column(Numeric(10, 6), nullable=False, default=0)

    __table_args__ = (
        UniqueConstraint("day", "feature", "brand_id", name="one_row_per_day_feature_brand"),
        CheckConstraint("cost_usd >= 0", name="spend_non_negative"),
        Index("ix_ai_spend_day", "day"),
    )


class Embedding(UUIDPrimaryKey, TimestampMixin, Base):
    """A vector for visual or semantic search.

    Produced by a self hosted open model, not by the Claude API, which has no
    embeddings endpoint. See docs/ai-architecture.md section 6.

    The ``dim`` column is stored alongside the vector because switching
    embedding models changes the dimension, and mixing dimensions in one
    similarity query returns nonsense rather than an error.
    """

    __tablename__ = "embeddings"

    owner_type: Mapped[EmbeddingOwner] = mapped_column(String(20), nullable=False)
    owner_id: Mapped[str] = mapped_column(String(36), nullable=False)
    # Denormalised for tenancy and for filtered similarity search.
    brand_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("brands.id", ondelete="CASCADE"), default=None
    )
    lot_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("lots.id", ondelete="CASCADE"), default=None
    )
    model: Mapped[str] = mapped_column(String(80), nullable=False)
    dim: Mapped[int] = mapped_column(Integer, nullable=False)
    vector: Mapped[list[float]] = mapped_column(Vector(768), nullable=False)

    __table_args__ = (
        UniqueConstraint("owner_type", "owner_id", "model", name="one_vector_per_owner_per_model"),
        Index("ix_embeddings_lot", "lot_id"),
        Index("ix_embeddings_owner", "owner_type", "owner_id"),
    )
