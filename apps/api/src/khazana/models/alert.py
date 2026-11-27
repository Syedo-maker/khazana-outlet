"""Alerts waiting to be emailed to the operator.

Written wherever something needs a person: a failed scheduled job, the AI
budget used up, a stale backup, a server error. The scheduler emails
undelivered rows every few minutes, so nothing in a request waits for SMTP.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, TimestampMixin, UUIDPrimaryKey


class Alert(UUIDPrimaryKey, TimestampMixin, Base):
    __tablename__ = "alerts"

    kind: Mapped[str] = mapped_column(String(80), nullable=False)
    subject: Mapped[str] = mapped_column(String(200), nullable=False)
    # No personal data: paths, job names and counts, never request bodies.
    body: Mapped[str] = mapped_column(Text, nullable=False, default="")
    # pending, sent, logged (no SMTP configured) or failed (gave up).
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_error: Mapped[str | None] = mapped_column(String(500), default=None)
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)

    __table_args__ = (
        Index("ix_alerts_kind_created", "kind", "created_at"),
        Index("ix_alerts_status", "status"),
    )
