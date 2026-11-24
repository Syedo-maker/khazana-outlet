"""Session hardening: refuse old access tokens, and count code requests by address.

``users.tokens_valid_after`` lets signing out everywhere, refresh token reuse
and suspension end every access token at once instead of when it expires.
``ix_otp_ip_created`` serves the per address limit on code requests.

Revision ID: 0017
Revises: 0016
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0017"
down_revision: str | None = "0016"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "users", sa.Column("tokens_valid_after", sa.DateTime(timezone=True), nullable=True)
    )
    op.create_index("ix_otp_ip_created", "otp_challenges", ["request_ip", "created_at"])


def downgrade() -> None:
    op.drop_index("ix_otp_ip_created", table_name="otp_challenges")
    op.drop_column("users", "tokens_valid_after")
