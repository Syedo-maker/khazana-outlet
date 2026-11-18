"""Track logo protection on lot photographs.

Revision ID: 0002
Revises: 0001
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("lot_photos") as batch:
        batch.add_column(
            sa.Column(
                "protection_status",
                sa.String(length=32),
                nullable=False,
                server_default="pending",
            )
        )
        batch.add_column(sa.Column("blurred_file_key", sa.String(length=500), nullable=True))
        batch.add_column(
            sa.Column(
                "protection_detail",
                sa.JSON().with_variant(postgresql.JSONB(), "postgresql"),
                nullable=True,
            )
        )
        batch.add_column(
            sa.Column("protection_reviewed_at", sa.DateTime(timezone=True), nullable=True)
        )
        batch.add_column(
            sa.Column("protection_reviewed_by_user_id", sa.String(length=36), nullable=True)
        )
        batch.create_foreign_key(
            "fk_lot_photos_protection_reviewed_by_user_id_users",
            "users",
            ["protection_reviewed_by_user_id"],
            ["id"],
            ondelete="SET NULL",
        )
        batch.create_check_constraint(
            "ck_lot_photos_protection_status_valid",
            "protection_status in ('pending', 'clear', 'blurred', 'needs_review', 'failed')",
        )
        # The default only exists to fill the rows already in the table.
        batch.alter_column("protection_status", server_default=None)


def downgrade() -> None:
    with op.batch_alter_table("lot_photos") as batch:
        batch.drop_constraint("ck_lot_photos_protection_status_valid", type_="check")
        batch.drop_constraint(
            "fk_lot_photos_protection_reviewed_by_user_id_users", type_="foreignkey"
        )
        batch.drop_column("protection_reviewed_by_user_id")
        batch.drop_column("protection_reviewed_at")
        batch.drop_column("protection_detail")
        batch.drop_column("blurred_file_key")
        batch.drop_column("protection_status")
