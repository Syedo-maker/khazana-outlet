"""Cases for a person to review: accounts, listings and orders that look wrong.

Scored by rules and, for listings, by the AI risk score. A case is only ever
a flag. Clearing it or acting on it is a decision an administrator makes and
records, and AI never suspends, pauses or cancels anything on its own.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, TimestampMixin, UUIDPrimaryKey
from .enums import ReviewStatus


class ReviewCase(UUIDPrimaryKey, TimestampMixin, Base):
    __tablename__ = "review_cases"

    # account, listing or order
    subject_type: Mapped[str] = mapped_column(String(16), nullable=False)
    subject_id: Mapped[str] = mapped_column(String(36), nullable=False)
    # Which brand a listing or order case concerns. Cases are read by
    # administrators only, never through a brand's own scope.
    brand_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("brands.id", ondelete="CASCADE"), default=None
    )
    score: Mapped[int] = mapped_column(Integer, nullable=False)
    # {"signals": [{"code": "...", "weight": 30, "detail": "..."}]}
    signals: Mapped[dict[str, Any]] = mapped_column(nullable=False)
    status: Mapped[ReviewStatus] = mapped_column(nullable=False, default=ReviewStatus.OPEN)
    decided_by_user_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="SET NULL"), default=None
    )
    decision_note: Mapped[str | None] = mapped_column(Text, default=None)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    scored_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (UniqueConstraint("subject_type", "subject_id", name="one_case_per_subject"),)
