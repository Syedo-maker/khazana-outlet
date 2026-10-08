"""The audit log.

Append only, with a before and after snapshot. Written by the service layer
for every consequential action: verification decisions, listing approvals,
order state changes, payouts, policy edits and role changes.

The initial migration adds a trigger that rejects UPDATE and DELETE on this
table, for the same reason as on listing approvals: an audit log that can be
rewritten proves nothing.
"""

from __future__ import annotations

from sqlalchemy import ForeignKey, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, TimestampMixin, UUIDPrimaryKey


class AuditLog(UUIDPrimaryKey, TimestampMixin, Base):
    __tablename__ = "audit_log"

    actor_user_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="SET NULL"), default=None
    )
    actor_role: Mapped[str | None] = mapped_column(String(16), default=None)
    # "system" for scheduled jobs, "ai" for anything a model initiated, so
    # that a model driven change is never indistinguishable from a human one.
    actor_kind: Mapped[str] = mapped_column(String(10), nullable=False, default="user")

    action: Mapped[str] = mapped_column(String(80), nullable=False)
    entity_type: Mapped[str] = mapped_column(String(40), nullable=False)
    entity_id: Mapped[str | None] = mapped_column(String(36), default=None)
    brand_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("brands.id", ondelete="SET NULL"), default=None
    )

    before: Mapped[dict[str, object] | None] = mapped_column(default=None)
    after: Mapped[dict[str, object] | None] = mapped_column(default=None)
    note: Mapped[str | None] = mapped_column(Text, default=None)
    ip: Mapped[str | None] = mapped_column(String(45), default=None)
    user_agent: Mapped[str | None] = mapped_column(String(255), default=None)

    __table_args__ = (
        Index("ix_audit_entity", "entity_type", "entity_id"),
        Index("ix_audit_brand_created", "brand_id", "created_at"),
        Index("ix_audit_actor_created", "actor_user_id", "created_at"),
        Index("ix_audit_action_created", "action", "created_at"),
    )
