"""The AI response cache, and batch tracking on AI jobs.

``ai_response_cache`` keeps a validated reply so an identical request is not
paid for twice; see ``AiResponseCache`` in models/ai.py for what the key
covers. ``ai_jobs.batch_id`` and ``prompt_ref`` track a job sent through the
Message Batches API until its reply comes back.

Revision ID: 0018
Revises: 0017
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0018"
down_revision: str | None = "0017"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "ai_response_cache",
        sa.Column("key", sa.String(length=64), nullable=False),
        sa.Column("feature", sa.String(length=32), nullable=False),
        sa.Column("model", sa.String(length=64), nullable=False),
        sa.Column(
            "output", sa.JSON().with_variant(postgresql.JSONB(), "postgresql"), nullable=False
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("hits", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("key"),
    )
    op.create_index("ix_ai_response_cache_expires_at", "ai_response_cache", ["expires_at"])
    op.add_column("ai_jobs", sa.Column("batch_id", sa.String(length=64), nullable=True))
    op.add_column("ai_jobs", sa.Column("prompt_ref", sa.String(length=64), nullable=True))
    op.create_index("ix_ai_jobs_batch_id", "ai_jobs", ["batch_id"])


def downgrade() -> None:
    op.drop_index("ix_ai_jobs_batch_id", table_name="ai_jobs")
    op.drop_column("ai_jobs", "prompt_ref")
    op.drop_column("ai_jobs", "batch_id")
    op.drop_index("ix_ai_response_cache_expires_at", table_name="ai_response_cache")
    op.drop_table("ai_response_cache")
