"""Single use invite links, and the terms each person accepted.

``invites`` replaces SMS login codes while there is no SMS gateway: an admin
creates a link and sends it by hand. ``users.terms_version`` and
``users.terms_accepted_at`` record which beta terms a person agreed to.

Revision ID: 0020
Revises: 0019
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0020"
down_revision: str | None = "0019"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "invites",
        sa.Column("token_hash", sa.String(length=255), nullable=False),
        sa.Column("purpose", sa.String(length=32), nullable=False),
        sa.Column("phone", sa.String(length=11), nullable=False),
        sa.Column("full_name", sa.String(length=120), nullable=True),
        sa.Column("role", sa.String(length=32), nullable=False),
        sa.Column("brand_id", sa.String(length=36), nullable=True),
        sa.Column("note", sa.String(length=300), nullable=True),
        sa.Column("created_by_user_id", sa.String(length=36), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("used_by_user_id", sa.String(length=36), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.String(length=36), nullable=False),
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
        sa.CheckConstraint(
            "role in ('brand', 'reseller') or (role = 'admin' and purpose = 'login')",
            name=op.f("ck_invites_invite_role_valid"),
        ),
        sa.ForeignKeyConstraint(
            ["brand_id"], ["brands.id"], name=op.f("fk_invites_brand_id_brands"), ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["created_by_user_id"],
            ["users.id"],
            name=op.f("fk_invites_created_by_user_id_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["used_by_user_id"],
            ["users.id"],
            name=op.f("fk_invites_used_by_user_id_users"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_invites")),
        sa.UniqueConstraint("token_hash", name=op.f("uq_invites_token_hash")),
    )
    op.create_index("ix_invites_phone_created", "invites", ["phone", "created_at"])

    with op.batch_alter_table("users") as batch:
        batch.add_column(sa.Column("terms_version", sa.String(length=32), nullable=True))
        batch.add_column(sa.Column("terms_accepted_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("users") as batch:
        batch.drop_column("terms_accepted_at")
        batch.drop_column("terms_version")
    op.drop_index("ix_invites_phone_created", table_name="invites")
    op.drop_table("invites")
