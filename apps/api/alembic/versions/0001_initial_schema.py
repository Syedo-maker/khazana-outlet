"""Initial schema.

Revision ID: 0001
Revises:
Create Date: 2026-10-08

This baseline migration creates the tables from the model metadata, then adds
the things SQLAlchemy models cannot express:

1. The pgvector extension and a similarity index, for visual search.
2. A deferred constraint trigger enforcing that a manifest sums to the lot
   total. Deferred rather than immediate, so a multi row insert is legal while
   it is in progress and is only checked at commit.
3. Append only triggers on the two audit tables.
4. Row level security policies for tenant isolation.

Subsequent migrations should use `alembic revision --autogenerate`, which
compares the models against the live database. Only this first one is built
from metadata.

This file was frozen on 2026-10-14. It used to call
`Base.metadata.create_all`, which built whatever the models happened to say at
the time, so it was a moving baseline rather than a record of a schema. The
consequences were real: a new column appeared automatically on a fresh
database and never on one that already existed, and writing a normal
`op.add_column` migration for it made `alembic upgrade head` fail on a
duplicate column. The development database was found missing
`lot_photos.checksum` for exactly that reason, and had to be patched by hand.

The tables are now written out. A schema change from here is a new migration
file, `alembic revision --autogenerate` produces a real diff, and it applies to
databases that already exist.

Two custom column types needed deciding rather than accepting what
autogenerate wrote. `EnumText` is a TypeDecorator whose impl is `String`, so
at DDL level it is exactly `VARCHAR(n)` and that is what this file says;
rendering the Python type produced a call that cannot be constructed without
its enum class and described nothing the database would see. `Vector` is
referenced directly, because it is a real pgvector column on PostgreSQL and
JSON on SQLite, and naming either one would break the other. `alembic/env.py`
now renders both correctly, so the next autogenerate does not repeat the
problem.

The revision identifier is deliberately unchanged, so a database already
stamped at 0001 stays valid and needs no re stamping. What the two versions
produce was compared column by column, index by index and constraint by
constraint before this landed.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# The embeddings vector column is a custom type that is a real pgvector column
# on PostgreSQL and JSON on SQLite, so the migration has to reference it rather
# than name a dialect specific type.
import khazana.models.base
from khazana.models import BRAND_SCOPED_TABLES

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


MANIFEST_BALANCE_FUNCTION = """
CREATE OR REPLACE FUNCTION khazana_check_manifest_balance() RETURNS trigger AS $$
DECLARE
    target_lot   text;
    declared     integer;
    counted      integer;
    lot_state    text;
BEGIN
    target_lot := COALESCE(NEW.lot_id, OLD.lot_id);

    SELECT total_pieces, status INTO declared, lot_state
    FROM lots WHERE id = target_lot;

    -- The lot itself was deleted in the same transaction, nothing to check.
    IF declared IS NULL THEN
        RETURN NULL;
    END IF;

    -- A draft is allowed to be unbalanced. The rule applies the moment a lot
    -- leaves draft, which is when a buyer could ever see it.
    IF lot_state = 'draft' THEN
        RETURN NULL;
    END IF;

    SELECT COALESCE(SUM(pieces), 0) INTO counted
    FROM manifest_lines WHERE lot_id = target_lot;

    IF counted <> declared THEN
        RAISE EXCEPTION
            'Manifest for lot % sums to % pieces but the lot declares %',
            target_lot, counted, declared;
    END IF;

    RETURN NULL;
END;
$$ LANGUAGE plpgsql;
"""

LOT_BALANCE_FUNCTION = """
CREATE OR REPLACE FUNCTION khazana_check_lot_balance() RETURNS trigger AS $$
DECLARE
    counted integer;
BEGIN
    IF NEW.status = 'draft' THEN
        RETURN NULL;
    END IF;

    SELECT COALESCE(SUM(pieces), 0) INTO counted
    FROM manifest_lines WHERE lot_id = NEW.id;

    IF counted <> NEW.total_pieces THEN
        RAISE EXCEPTION
            'Lot % declares % pieces but its manifest sums to %',
            NEW.id, NEW.total_pieces, counted;
    END IF;

    RETURN NULL;
END;
$$ LANGUAGE plpgsql;
"""

APPEND_ONLY_FUNCTION = """
CREATE OR REPLACE FUNCTION khazana_reject_mutation() RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION
        'Table % is append only. Insert a new row instead of changing history.',
        TG_TABLE_NAME;
END;
$$ LANGUAGE plpgsql;
"""


def upgrade() -> None:
    bind = op.get_bind()
    is_postgres = bind.dialect.name == "postgresql"

    if is_postgres:
        op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    # The tables, written out rather than generated from the models.
    #
    # This used to be Base.metadata.create_all(bind), which built whatever
    # the models happened to say when it ran. That made this file a moving
    # baseline rather than a record: a new column appeared automatically on
    # a fresh database and never on one that already existed, and writing a
    # normal op.add_column migration for it made upgrade head fail on a
    # duplicate column. The development database was found missing
    # lot_photos.checksum for exactly that reason.
    #
    # Generated once from the models with alembic revision --autogenerate
    # and frozen here. From now on a schema change is a new migration, and
    # it applies to databases that already exist.
    op.create_table(
        "categories",
        sa.Column("parent_id", sa.String(length=36), nullable=True),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("slug", sa.String(length=120), nullable=False),
        sa.Column("requires_expiry", sa.Boolean(), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False),
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
        sa.ForeignKeyConstraint(
            ["parent_id"],
            ["categories.id"],
            name=op.f("fk_categories_parent_id_categories"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_categories")),
        sa.UniqueConstraint("slug", name=op.f("uq_categories_slug")),
    )
    op.create_index("ix_categories_parent", "categories", ["parent_id"], unique=False)
    op.create_table(
        "otp_challenges",
        sa.Column("phone", sa.String(length=11), nullable=False),
        sa.Column("code_hash", sa.String(length=255), nullable=False),
        sa.Column("purpose", sa.String(length=32), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("request_ip", sa.String(length=45), nullable=True),
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
        sa.CheckConstraint("attempts >= 0", name=op.f("ck_otp_challenges_attempts_non_negative")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_otp_challenges")),
    )
    op.create_index("ix_otp_phone_created", "otp_challenges", ["phone", "created_at"], unique=False)
    op.create_table(
        "users",
        sa.Column("phone", sa.String(length=11), nullable=False),
        sa.Column("email", sa.String(length=255), nullable=True),
        sa.Column("full_name", sa.String(length=120), nullable=False),
        sa.Column("role", sa.String(length=32), nullable=False),
        sa.Column("password_hash", sa.String(length=255), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("phone_verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("preferred_language", sa.String(length=8), nullable=False),
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
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "preferred_language in ('en', 'ur', 'ur_roman')", name=op.f("ck_users_language_valid")
        ),
        sa.CheckConstraint(
            "role in ('brand', 'reseller', 'admin')", name=op.f("ck_users_role_valid")
        ),
        sa.CheckConstraint("length(phone) = 11", name=op.f("ck_users_phone_length")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_users")),
        sa.UniqueConstraint("email", name=op.f("uq_users_email")),
        sa.UniqueConstraint("phone", name=op.f("uq_users_phone")),
    )
    op.create_index("ix_users_role_active", "users", ["role", "is_active"], unique=False)
    op.create_table(
        "brands",
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column("legal_name", sa.String(length=200), nullable=True),
        sa.Column("slug", sa.String(length=160), nullable=False),
        sa.Column("ntn", sa.String(length=32), nullable=True),
        sa.Column("city", sa.String(length=80), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("unbranded_label", sa.String(length=160), nullable=True),
        sa.Column("contact_phone", sa.String(length=11), nullable=True),
        sa.Column("contact_email", sa.String(length=255), nullable=True),
        sa.Column("reviewed_by_user_id", sa.String(length=36), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("review_note", sa.String(length=500), nullable=True),
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
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["reviewed_by_user_id"],
            ["users.id"],
            name=op.f("fk_brands_reviewed_by_user_id_users"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_brands")),
        sa.UniqueConstraint("slug", name=op.f("uq_brands_slug")),
    )
    op.create_index("ix_brands_status_city", "brands", ["status", "city"], unique=False)
    op.create_table(
        "reseller_profiles",
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("business_name", sa.String(length=160), nullable=False),
        sa.Column("city", sa.String(length=80), nullable=False),
        sa.Column("ntn", sa.String(length=32), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("monthly_purchase_pkr", sa.Integer(), nullable=True),
        sa.Column("shop_address", sa.String(length=255), nullable=True),
        sa.Column("reviewed_by_user_id", sa.String(length=36), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("review_note", sa.String(length=500), nullable=True),
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
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["reviewed_by_user_id"],
            ["users.id"],
            name=op.f("fk_reseller_profiles_reviewed_by_user_id_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_reseller_profiles_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_reseller_profiles")),
        sa.UniqueConstraint("user_id", name="one_profile_per_user"),
        sa.UniqueConstraint("user_id", name=op.f("uq_reseller_profiles_user_id")),
    )
    op.create_index(
        "ix_reseller_status_city", "reseller_profiles", ["status", "city"], unique=False
    )
    op.create_table(
        "sessions",
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("token_hash", sa.String(length=255), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("user_agent", sa.String(length=255), nullable=True),
        sa.Column("ip", sa.String(length=45), nullable=True),
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
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_sessions_user_id_users"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_sessions")),
        sa.UniqueConstraint("token_hash", name=op.f("uq_sessions_token_hash")),
    )
    op.create_index("ix_sessions_user_revoked", "sessions", ["user_id", "revoked_at"], unique=False)
    op.create_table(
        "ai_jobs",
        sa.Column("feature", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("mode", sa.String(length=32), nullable=False),
        sa.Column("entity_type", sa.String(length=40), nullable=True),
        sa.Column("entity_id", sa.String(length=36), nullable=True),
        sa.Column("brand_id", sa.String(length=36), nullable=True),
        sa.Column("requested_by_user_id", sa.String(length=36), nullable=True),
        sa.Column("blocked_reason", sa.String(length=255), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
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
        sa.ForeignKeyConstraint(
            ["brand_id"],
            ["brands.id"],
            name=op.f("fk_ai_jobs_brand_id_brands"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["requested_by_user_id"],
            ["users.id"],
            name=op.f("fk_ai_jobs_requested_by_user_id_users"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_ai_jobs")),
    )
    op.create_index("ix_ai_jobs_brand_created", "ai_jobs", ["brand_id", "created_at"], unique=False)
    op.create_index("ix_ai_jobs_entity", "ai_jobs", ["entity_type", "entity_id"], unique=False)
    op.create_index("ix_ai_jobs_feature_status", "ai_jobs", ["feature", "status"], unique=False)
    op.create_table(
        "ai_spend",
        sa.Column("day", sa.Date(), nullable=False),
        sa.Column("feature", sa.String(length=32), nullable=False),
        sa.Column("brand_id", sa.String(length=36), nullable=True),
        sa.Column("calls", sa.Integer(), nullable=False),
        sa.Column("cost_usd", sa.Numeric(precision=10, scale=6), nullable=False),
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
        sa.CheckConstraint("cost_usd >= 0", name=op.f("ck_ai_spend_spend_non_negative")),
        sa.ForeignKeyConstraint(
            ["brand_id"],
            ["brands.id"],
            name=op.f("fk_ai_spend_brand_id_brands"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_ai_spend")),
        sa.UniqueConstraint("day", "feature", "brand_id", name="one_row_per_day_feature_brand"),
    )
    op.create_index("ix_ai_spend_day", "ai_spend", ["day"], unique=False)
    op.create_table(
        "audit_log",
        sa.Column("actor_user_id", sa.String(length=36), nullable=True),
        sa.Column("actor_role", sa.String(length=16), nullable=True),
        sa.Column("actor_kind", sa.String(length=10), nullable=False),
        sa.Column("action", sa.String(length=80), nullable=False),
        sa.Column("entity_type", sa.String(length=40), nullable=False),
        sa.Column("entity_id", sa.String(length=36), nullable=True),
        sa.Column("brand_id", sa.String(length=36), nullable=True),
        sa.Column(
            "before",
            sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql"),
            nullable=True,
        ),
        sa.Column(
            "after",
            sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql"),
            nullable=True,
        ),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("ip", sa.String(length=45), nullable=True),
        sa.Column("user_agent", sa.String(length=255), nullable=True),
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
        sa.ForeignKeyConstraint(
            ["actor_user_id"],
            ["users.id"],
            name=op.f("fk_audit_log_actor_user_id_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["brand_id"],
            ["brands.id"],
            name=op.f("fk_audit_log_brand_id_brands"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_audit_log")),
    )
    op.create_index("ix_audit_action_created", "audit_log", ["action", "created_at"], unique=False)
    op.create_index(
        "ix_audit_actor_created", "audit_log", ["actor_user_id", "created_at"], unique=False
    )
    op.create_index("ix_audit_brand_created", "audit_log", ["brand_id", "created_at"], unique=False)
    op.create_index("ix_audit_entity", "audit_log", ["entity_type", "entity_id"], unique=False)
    op.create_table(
        "brand_excluded_cities",
        sa.Column("brand_id", sa.String(length=36), nullable=False),
        sa.Column("city", sa.String(length=80), nullable=False),
        sa.Column("reason", sa.String(length=255), nullable=True),
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
        sa.ForeignKeyConstraint(
            ["brand_id"],
            ["brands.id"],
            name=op.f("fk_brand_excluded_cities_brand_id_brands"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_brand_excluded_cities")),
        sa.UniqueConstraint("brand_id", "city", name="one_exclusion_per_city_per_brand"),
    )
    op.create_table(
        "brand_members",
        sa.Column("brand_id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("role_in_brand", sa.String(length=32), nullable=False),
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
        sa.ForeignKeyConstraint(
            ["brand_id"],
            ["brands.id"],
            name=op.f("fk_brand_members_brand_id_brands"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_brand_members_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_brand_members")),
        sa.UniqueConstraint("brand_id", "user_id", name="one_membership_per_user_per_brand"),
    )
    op.create_index("ix_brand_members_user", "brand_members", ["user_id"], unique=False)
    op.create_table(
        "brand_policies",
        sa.Column("brand_id", sa.String(length=36), nullable=False),
        sa.Column("commission_percent", sa.Numeric(precision=5, scale=2), nullable=False),
        sa.Column("payout_terms_days", sa.Integer(), nullable=False),
        sa.Column("min_lot_value_pkr", sa.Integer(), nullable=False),
        sa.Column("min_discount_percent", sa.Numeric(precision=5, scale=2), nullable=False),
        sa.Column("max_discount_percent", sa.Numeric(precision=5, scale=2), nullable=False),
        sa.Column("default_visibility", sa.String(length=32), nullable=False),
        sa.Column("require_brand_approval", sa.Boolean(), nullable=False),
        sa.Column("allow_cod", sa.Boolean(), nullable=False),
        sa.Column("allow_part_lot_orders", sa.Boolean(), nullable=False),
        sa.Column("auto_apply_ai_draft", sa.Boolean(), nullable=False),
        sa.Column("ai_monthly_budget_usd", sa.Numeric(precision=8, scale=2), nullable=False),
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
            "commission_percent >= 0 and commission_percent <= 50",
            name=op.f("ck_brand_policies_commission_in_range"),
        ),
        sa.CheckConstraint(
            "min_discount_percent < max_discount_percent",
            name=op.f("ck_brand_policies_discount_band_ordered"),
        ),
        sa.CheckConstraint(
            "min_lot_value_pkr >= 0", name=op.f("ck_brand_policies_min_lot_value_non_negative")
        ),
        sa.CheckConstraint(
            "payout_terms_days >= 0", name=op.f("ck_brand_policies_payout_terms_non_negative")
        ),
        sa.CheckConstraint(
            "require_brand_approval = true", name=op.f("ck_brand_policies_approval_gate_mandatory")
        ),
        sa.ForeignKeyConstraint(
            ["brand_id"],
            ["brands.id"],
            name=op.f("fk_brand_policies_brand_id_brands"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_brand_policies")),
        sa.UniqueConstraint("brand_id", name=op.f("uq_brand_policies_brand_id")),
    )
    op.create_table(
        "lots",
        sa.Column("lot_code", sa.String(length=24), nullable=False),
        sa.Column("brand_id", sa.String(length=36), nullable=False),
        sa.Column("category_id", sa.String(length=36), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("season", sa.String(length=40), nullable=True),
        sa.Column("condition_grade", sa.String(length=32), nullable=False),
        sa.Column("total_pieces", sa.Integer(), nullable=False),
        sa.Column("retail_price_per_piece_pkr", sa.Integer(), nullable=False),
        sa.Column("lot_price_pkr", sa.Integer(), nullable=False),
        sa.Column("min_order_pieces", sa.Integer(), nullable=False),
        sa.Column("stock_city", sa.String(length=80), nullable=False),
        sa.Column("weight_kg", sa.Numeric(precision=8, scale=2), nullable=True),
        sa.Column("cartons", sa.Integer(), nullable=True),
        sa.Column("expiry_date", sa.Date(), nullable=True),
        sa.Column("available_until", sa.Date(), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("visibility", sa.String(length=32), nullable=False),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("approved_by_user_id", sa.String(length=36), nullable=True),
        sa.Column("created_by_user_id", sa.String(length=36), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False),
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
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("condition_grade in ('A', 'B', 'C')", name=op.f("ck_lots_grade_valid")),
        sa.CheckConstraint(
            "status <> 'live' or approved_at is not null",
            name=op.f("ck_lots_live_requires_approval"),
        ),
        sa.CheckConstraint(
            "visibility in ('public', 'private', 'unbranded')",
            name=op.f("ck_lots_visibility_valid"),
        ),
        sa.CheckConstraint(
            "lot_price_pkr <= retail_price_per_piece_pkr * total_pieces",
            name=op.f("ck_lots_lot_price_not_above_retail"),
        ),
        sa.CheckConstraint("lot_price_pkr > 0", name=op.f("ck_lots_lot_price_positive")),
        sa.CheckConstraint(
            "min_order_pieces > 0 and min_order_pieces <= total_pieces",
            name=op.f("ck_lots_min_order_within_lot"),
        ),
        sa.CheckConstraint(
            "retail_price_per_piece_pkr > 0", name=op.f("ck_lots_retail_price_positive")
        ),
        sa.CheckConstraint("total_pieces > 0", name=op.f("ck_lots_total_pieces_positive")),
        sa.ForeignKeyConstraint(
            ["approved_by_user_id"],
            ["users.id"],
            name=op.f("fk_lots_approved_by_user_id_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["brand_id"], ["brands.id"], name=op.f("fk_lots_brand_id_brands"), ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["category_id"],
            ["categories.id"],
            name=op.f("fk_lots_category_id_categories"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_user_id"],
            ["users.id"],
            name=op.f("fk_lots_created_by_user_id_users"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_lots")),
        sa.UniqueConstraint("lot_code", name=op.f("uq_lots_lot_code")),
    )
    op.create_index("ix_lots_brand_status", "lots", ["brand_id", "status"], unique=False)
    op.create_index("ix_lots_browse", "lots", ["status", "visibility", "category_id"], unique=False)
    op.create_index("ix_lots_city", "lots", ["stock_city"], unique=False)
    op.create_table(
        "verification_documents",
        sa.Column("brand_id", sa.String(length=36), nullable=False),
        sa.Column("doc_type", sa.String(length=32), nullable=False),
        sa.Column("file_key", sa.String(length=500), nullable=False),
        sa.Column("original_filename", sa.String(length=255), nullable=True),
        sa.Column("content_type", sa.String(length=100), nullable=True),
        sa.Column("size_bytes", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("uploaded_by_user_id", sa.String(length=36), nullable=True),
        sa.Column("reviewed_by_user_id", sa.String(length=36), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("review_note", sa.String(length=500), nullable=True),
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
        sa.ForeignKeyConstraint(
            ["brand_id"],
            ["brands.id"],
            name=op.f("fk_verification_documents_brand_id_brands"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["reviewed_by_user_id"],
            ["users.id"],
            name=op.f("fk_verification_documents_reviewed_by_user_id_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["uploaded_by_user_id"],
            ["users.id"],
            name=op.f("fk_verification_documents_uploaded_by_user_id_users"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_verification_documents")),
    )
    op.create_index(
        "ix_docs_brand_status", "verification_documents", ["brand_id", "status"], unique=False
    )
    op.create_table(
        "ai_outputs",
        sa.Column("job_id", sa.String(length=36), nullable=False),
        sa.Column("model", sa.String(length=60), nullable=False),
        sa.Column("prompt_name", sa.String(length=80), nullable=False),
        sa.Column("prompt_version", sa.Integer(), nullable=False),
        sa.Column("effort", sa.String(length=10), nullable=True),
        sa.Column("input_tokens", sa.Integer(), nullable=False),
        sa.Column("output_tokens", sa.Integer(), nullable=False),
        sa.Column("cache_read_tokens", sa.Integer(), nullable=False),
        sa.Column("cache_write_tokens", sa.Integer(), nullable=False),
        sa.Column("cost_usd", sa.Numeric(precision=10, scale=6), nullable=False),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.Column(
            "output",
            sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql"),
            nullable=True,
        ),
        sa.Column("accepted", sa.Boolean(), nullable=True),
        sa.Column(
            "human_corrected",
            sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql"),
            nullable=True,
        ),
        sa.Column("reviewed_by_user_id", sa.String(length=36), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
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
        sa.CheckConstraint("cost_usd >= 0", name=op.f("ck_ai_outputs_cost_non_negative")),
        sa.CheckConstraint(
            "input_tokens >= 0", name=op.f("ck_ai_outputs_input_tokens_non_negative")
        ),
        sa.CheckConstraint(
            "output_tokens >= 0", name=op.f("ck_ai_outputs_output_tokens_non_negative")
        ),
        sa.ForeignKeyConstraint(
            ["job_id"],
            ["ai_jobs.id"],
            name=op.f("fk_ai_outputs_job_id_ai_jobs"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["reviewed_by_user_id"],
            ["users.id"],
            name=op.f("fk_ai_outputs_reviewed_by_user_id_users"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_ai_outputs")),
    )
    op.create_index("ix_ai_outputs_accepted", "ai_outputs", ["accepted"], unique=False)
    op.create_index(
        "ix_ai_outputs_prompt", "ai_outputs", ["prompt_name", "prompt_version"], unique=False
    )
    op.create_table(
        "embeddings",
        sa.Column("owner_type", sa.String(length=32), nullable=False),
        sa.Column("owner_id", sa.String(length=36), nullable=False),
        sa.Column("brand_id", sa.String(length=36), nullable=True),
        sa.Column("lot_id", sa.String(length=36), nullable=True),
        sa.Column("model", sa.String(length=80), nullable=False),
        sa.Column("dim", sa.Integer(), nullable=False),
        sa.Column("vector", khazana.models.base.Vector(), nullable=False),
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
        sa.ForeignKeyConstraint(
            ["brand_id"],
            ["brands.id"],
            name=op.f("fk_embeddings_brand_id_brands"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["lot_id"], ["lots.id"], name=op.f("fk_embeddings_lot_id_lots"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_embeddings")),
        sa.UniqueConstraint(
            "owner_type", "owner_id", "model", name="one_vector_per_owner_per_model"
        ),
    )
    op.create_index("ix_embeddings_lot", "embeddings", ["lot_id"], unique=False)
    op.create_index("ix_embeddings_owner", "embeddings", ["owner_type", "owner_id"], unique=False)
    op.create_table(
        "listing_approvals",
        sa.Column("lot_id", sa.String(length=36), nullable=False),
        sa.Column("brand_id", sa.String(length=36), nullable=False),
        sa.Column("action", sa.String(length=32), nullable=False),
        sa.Column("actor_user_id", sa.String(length=36), nullable=True),
        sa.Column("actor_role", sa.String(length=16), nullable=False),
        sa.Column("visibility_at_action", sa.String(length=32), nullable=False),
        sa.Column("note", sa.String(length=500), nullable=True),
        sa.Column(
            "snapshot",
            sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql"),
            nullable=True,
        ),
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
        sa.ForeignKeyConstraint(
            ["actor_user_id"],
            ["users.id"],
            name=op.f("fk_listing_approvals_actor_user_id_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["brand_id"],
            ["brands.id"],
            name=op.f("fk_listing_approvals_brand_id_brands"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["lot_id"],
            ["lots.id"],
            name=op.f("fk_listing_approvals_lot_id_lots"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_listing_approvals")),
    )
    op.create_index(
        "ix_approvals_lot_created", "listing_approvals", ["lot_id", "created_at"], unique=False
    )
    op.create_table(
        "lot_excluded_cities",
        sa.Column("lot_id", sa.String(length=36), nullable=False),
        sa.Column("brand_id", sa.String(length=36), nullable=False),
        sa.Column("city", sa.String(length=80), nullable=False),
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
        sa.ForeignKeyConstraint(
            ["brand_id"],
            ["brands.id"],
            name=op.f("fk_lot_excluded_cities_brand_id_brands"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["lot_id"],
            ["lots.id"],
            name=op.f("fk_lot_excluded_cities_lot_id_lots"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_lot_excluded_cities")),
        sa.UniqueConstraint("lot_id", "city", name="one_exclusion_per_city_per_lot"),
    )
    op.create_table(
        "lot_photos",
        sa.Column("lot_id", sa.String(length=36), nullable=False),
        sa.Column("brand_id", sa.String(length=36), nullable=False),
        sa.Column("file_key", sa.String(length=500), nullable=False),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        sa.Column("width", sa.Integer(), nullable=True),
        sa.Column("height", sa.Integer(), nullable=True),
        sa.Column("bytes_stored", sa.Integer(), nullable=True),
        sa.Column("is_optimised", sa.Boolean(), nullable=False),
        sa.Column("checksum", sa.String(length=64), nullable=True),
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
        sa.ForeignKeyConstraint(
            ["brand_id"],
            ["brands.id"],
            name=op.f("fk_lot_photos_brand_id_brands"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["lot_id"], ["lots.id"], name=op.f("fk_lot_photos_lot_id_lots"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_lot_photos")),
    )
    op.create_index("ix_photos_lot_checksum", "lot_photos", ["lot_id", "checksum"], unique=False)
    op.create_index("ix_photos_lot_order", "lot_photos", ["lot_id", "sort_order"], unique=False)
    op.create_table(
        "manifest_lines",
        sa.Column("lot_id", sa.String(length=36), nullable=False),
        sa.Column("brand_id", sa.String(length=36), nullable=False),
        sa.Column("size", sa.String(length=32), nullable=False),
        sa.Column("color", sa.String(length=48), nullable=False),
        sa.Column("pieces", sa.Integer(), nullable=False),
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
        sa.CheckConstraint("pieces > 0", name=op.f("ck_manifest_lines_pieces_positive")),
        sa.ForeignKeyConstraint(
            ["brand_id"],
            ["brands.id"],
            name=op.f("fk_manifest_lines_brand_id_brands"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["lot_id"], ["lots.id"], name=op.f("fk_manifest_lines_lot_id_lots"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_manifest_lines")),
        sa.UniqueConstraint("lot_id", "size", "color", name="one_line_per_size_colour"),
    )
    op.create_index("ix_manifest_lot", "manifest_lines", ["lot_id"], unique=False)
    op.create_table(
        "orders",
        sa.Column("order_code", sa.String(length=24), nullable=False),
        sa.Column("lot_id", sa.String(length=36), nullable=False),
        sa.Column("brand_id", sa.String(length=36), nullable=False),
        sa.Column("buyer_user_id", sa.String(length=36), nullable=False),
        sa.Column("pieces", sa.Integer(), nullable=False),
        sa.Column("unit_price_pkr", sa.Integer(), nullable=False),
        sa.Column("subtotal_pkr", sa.Integer(), nullable=False),
        sa.Column("shipping_pkr", sa.Integer(), nullable=False),
        sa.Column("total_pkr", sa.Integer(), nullable=False),
        sa.Column("commission_percent", sa.Numeric(precision=5, scale=2), nullable=False),
        sa.Column("commission_pkr", sa.Integer(), nullable=False),
        sa.Column("brand_payout_pkr", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("delivery_city", sa.String(length=80), nullable=False),
        sa.Column("delivery_address", sa.String(length=500), nullable=False),
        sa.Column("delivery_phone", sa.String(length=11), nullable=False),
        sa.Column("dispute_window_ends_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancellation_reason", sa.String(length=500), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False),
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
            "brand_payout_pkr = subtotal_pkr - commission_pkr",
            name=op.f("ck_orders_order_payout_consistent"),
        ),
        sa.CheckConstraint(
            "commission_pkr >= 0", name=op.f("ck_orders_order_commission_non_negative")
        ),
        sa.CheckConstraint("pieces > 0", name=op.f("ck_orders_order_pieces_positive")),
        sa.CheckConstraint("shipping_pkr >= 0", name=op.f("ck_orders_order_shipping_non_negative")),
        sa.CheckConstraint(
            "subtotal_pkr = pieces * unit_price_pkr",
            name=op.f("ck_orders_order_subtotal_consistent"),
        ),
        sa.CheckConstraint(
            "total_pkr = subtotal_pkr + shipping_pkr", name=op.f("ck_orders_order_total_consistent")
        ),
        sa.CheckConstraint("unit_price_pkr > 0", name=op.f("ck_orders_order_unit_price_positive")),
        sa.ForeignKeyConstraint(
            ["brand_id"], ["brands.id"], name=op.f("fk_orders_brand_id_brands"), ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["buyer_user_id"],
            ["users.id"],
            name=op.f("fk_orders_buyer_user_id_users"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["lot_id"], ["lots.id"], name=op.f("fk_orders_lot_id_lots"), ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_orders")),
        sa.UniqueConstraint("order_code", name=op.f("uq_orders_order_code")),
    )
    op.create_index("ix_orders_brand_status", "orders", ["brand_id", "status"], unique=False)
    op.create_index(
        "ix_orders_buyer_created", "orders", ["buyer_user_id", "created_at"], unique=False
    )
    op.create_index("ix_orders_lot", "orders", ["lot_id"], unique=False)
    op.create_table(
        "disputes",
        sa.Column("order_id", sa.String(length=36), nullable=False),
        sa.Column("brand_id", sa.String(length=36), nullable=False),
        sa.Column("raised_by_user_id", sa.String(length=36), nullable=False),
        sa.Column("reason", sa.String(length=120), nullable=False),
        sa.Column("detail", sa.Text(), nullable=True),
        sa.Column(
            "evidence_keys",
            sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql"),
            nullable=True,
        ),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("resolution", sa.Text(), nullable=True),
        sa.Column("refund_pkr", sa.Integer(), nullable=True),
        sa.Column("resolved_by_user_id", sa.String(length=36), nullable=True),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
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
            "refund_pkr is null or refund_pkr >= 0", name=op.f("ck_disputes_refund_non_negative")
        ),
        sa.ForeignKeyConstraint(
            ["brand_id"],
            ["brands.id"],
            name=op.f("fk_disputes_brand_id_brands"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["order_id"],
            ["orders.id"],
            name=op.f("fk_disputes_order_id_orders"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["raised_by_user_id"],
            ["users.id"],
            name=op.f("fk_disputes_raised_by_user_id_users"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["resolved_by_user_id"],
            ["users.id"],
            name=op.f("fk_disputes_resolved_by_user_id_users"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_disputes")),
    )
    op.create_index(
        "ix_disputes_status_created", "disputes", ["status", "created_at"], unique=False
    )
    op.create_table(
        "lot_defects",
        sa.Column("lot_id", sa.String(length=36), nullable=False),
        sa.Column("brand_id", sa.String(length=36), nullable=False),
        sa.Column("issue", sa.String(length=255), nullable=False),
        sa.Column("pieces_affected", sa.Integer(), nullable=False),
        sa.Column("photo_id", sa.String(length=36), nullable=True),
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
            "pieces_affected > 0", name=op.f("ck_lot_defects_defect_pieces_positive")
        ),
        sa.ForeignKeyConstraint(
            ["brand_id"],
            ["brands.id"],
            name=op.f("fk_lot_defects_brand_id_brands"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["lot_id"], ["lots.id"], name=op.f("fk_lot_defects_lot_id_lots"), ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["photo_id"],
            ["lot_photos.id"],
            name=op.f("fk_lot_defects_photo_id_lot_photos"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_lot_defects")),
    )
    op.create_index("ix_defects_lot", "lot_defects", ["lot_id"], unique=False)
    op.create_table(
        "order_lines",
        sa.Column("order_id", sa.String(length=36), nullable=False),
        sa.Column("brand_id", sa.String(length=36), nullable=False),
        sa.Column("size", sa.String(length=32), nullable=False),
        sa.Column("color", sa.String(length=48), nullable=False),
        sa.Column("pieces", sa.Integer(), nullable=False),
        sa.Column("unit_price_pkr", sa.Integer(), nullable=False),
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
        sa.CheckConstraint("pieces > 0", name=op.f("ck_order_lines_order_line_pieces_positive")),
        sa.ForeignKeyConstraint(
            ["brand_id"],
            ["brands.id"],
            name=op.f("fk_order_lines_brand_id_brands"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["order_id"],
            ["orders.id"],
            name=op.f("fk_order_lines_order_id_orders"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_order_lines")),
        sa.UniqueConstraint("order_id", "size", "color", name="one_order_line_per_size_colour"),
    )
    op.create_table(
        "payments",
        sa.Column("order_id", sa.String(length=36), nullable=False),
        sa.Column("method", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("amount_pkr", sa.Integer(), nullable=False),
        sa.Column("provider", sa.String(length=40), nullable=True),
        sa.Column("provider_reference", sa.String(length=120), nullable=True),
        sa.Column("held_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("released_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("refunded_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("failure_reason", sa.String(length=500), nullable=True),
        sa.Column(
            "provider_payload",
            sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql"),
            nullable=True,
        ),
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
        sa.CheckConstraint("amount_pkr > 0", name=op.f("ck_payments_payment_amount_positive")),
        sa.ForeignKeyConstraint(
            ["order_id"],
            ["orders.id"],
            name=op.f("fk_payments_order_id_orders"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_payments")),
        sa.UniqueConstraint(
            "provider", "provider_reference", name="one_payment_per_provider_reference"
        ),
    )
    op.create_index("ix_payments_order_status", "payments", ["order_id", "status"], unique=False)
    op.create_table(
        "payouts",
        sa.Column("order_id", sa.String(length=36), nullable=False),
        sa.Column("brand_id", sa.String(length=36), nullable=False),
        sa.Column("amount_pkr", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("scheduled_for", sa.DateTime(timezone=True), nullable=True),
        sa.Column("paid_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reference", sa.String(length=120), nullable=True),
        sa.Column("note", sa.String(length=500), nullable=True),
        sa.Column("approved_by_user_id", sa.String(length=36), nullable=True),
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
        sa.CheckConstraint("amount_pkr >= 0", name=op.f("ck_payouts_payout_amount_non_negative")),
        sa.ForeignKeyConstraint(
            ["approved_by_user_id"],
            ["users.id"],
            name=op.f("fk_payouts_approved_by_user_id_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["brand_id"],
            ["brands.id"],
            name=op.f("fk_payouts_brand_id_brands"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["order_id"],
            ["orders.id"],
            name=op.f("fk_payouts_order_id_orders"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_payouts")),
        sa.UniqueConstraint("order_id", name=op.f("uq_payouts_order_id")),
    )
    op.create_index("ix_payouts_brand_status", "payouts", ["brand_id", "status"], unique=False)
    op.create_table(
        "shipments",
        sa.Column("order_id", sa.String(length=36), nullable=False),
        sa.Column("brand_id", sa.String(length=36), nullable=False),
        sa.Column("courier", sa.String(length=40), nullable=False),
        sa.Column("tracking_number", sa.String(length=80), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("cost_pkr", sa.Integer(), nullable=True),
        sa.Column("cartons", sa.Integer(), nullable=True),
        sa.Column("weight_kg", sa.Numeric(precision=8, scale=2), nullable=True),
        sa.Column("label_key", sa.String(length=500), nullable=True),
        sa.Column("picked_up_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("delivered_at", sa.DateTime(timezone=True), nullable=True),
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
        sa.ForeignKeyConstraint(
            ["brand_id"],
            ["brands.id"],
            name=op.f("fk_shipments_brand_id_brands"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["order_id"],
            ["orders.id"],
            name=op.f("fk_shipments_order_id_orders"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_shipments")),
        sa.UniqueConstraint("courier", "tracking_number", name="one_shipment_per_tracking_number"),
    )
    op.create_index("ix_shipments_order", "shipments", ["order_id"], unique=False)
    # ### end Alembic commands ###

    if not is_postgres:
        # SQLite is used for tests only. The triggers and policies below are
        # PostgreSQL features; the equivalent rules are enforced in the
        # service layer and covered by tests on both engines.
        return

    # ---------- Manifest integrity ----------
    op.execute(MANIFEST_BALANCE_FUNCTION)
    op.execute(LOT_BALANCE_FUNCTION)
    op.execute(
        """
        CREATE CONSTRAINT TRIGGER trg_manifest_lines_balance
        AFTER INSERT OR UPDATE OR DELETE ON manifest_lines
        DEFERRABLE INITIALLY DEFERRED
        FOR EACH ROW EXECUTE FUNCTION khazana_check_manifest_balance()
        """
    )
    op.execute(
        """
        CREATE CONSTRAINT TRIGGER trg_lots_balance
        AFTER INSERT OR UPDATE ON lots
        DEFERRABLE INITIALLY DEFERRED
        FOR EACH ROW EXECUTE FUNCTION khazana_check_lot_balance()
        """
    )

    # ---------- Append only audit tables ----------
    op.execute(APPEND_ONLY_FUNCTION)
    for table in ("listing_approvals", "audit_log"):
        op.execute(
            f"""
            CREATE TRIGGER trg_{table}_append_only
            BEFORE UPDATE OR DELETE ON {table}
            FOR EACH STATEMENT EXECUTE FUNCTION khazana_reject_mutation()
            """
        )

    # ---------- Vector similarity index ----------
    op.execute(
        """
        CREATE INDEX ix_embeddings_vector_cosine
        ON embeddings USING hnsw (vector vector_cosine_ops)
        """
    )

    # ---------- Row level security ----------
    # Defence in depth, not the primary control. The repository layer always
    # filters by brand and the isolation tests prove it. These policies catch
    # the case where a future query forgets.
    #
    # For the policies to apply, the application must connect as a role that
    # does not own the tables, because PostgreSQL exempts table owners unless
    # FORCE ROW LEVEL SECURITY is set. See docs/deployment.md for the
    # khazana_app role. Migrations and seeding intentionally run as the owner.
    for table in BRAND_SCOPED_TABLES:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(
            f"""
            CREATE POLICY {table}_tenant_isolation ON {table}
            USING (
                current_setting('khazana.role', true) = 'admin'
                OR brand_id = current_setting('khazana.brand_id', true)
            )
            """
        )


def downgrade() -> None:
    bind = op.get_bind()
    is_postgres = bind.dialect.name == "postgresql"

    if is_postgres:
        for table in BRAND_SCOPED_TABLES:
            op.execute(f"DROP POLICY IF EXISTS {table}_tenant_isolation ON {table}")
            op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY")

        op.execute("DROP INDEX IF EXISTS ix_embeddings_vector_cosine")

        for table in ("listing_approvals", "audit_log"):
            op.execute(f"DROP TRIGGER IF EXISTS trg_{table}_append_only ON {table}")
        op.execute("DROP TRIGGER IF EXISTS trg_lots_balance ON lots")
        op.execute("DROP TRIGGER IF EXISTS trg_manifest_lines_balance ON manifest_lines")

        op.execute("DROP FUNCTION IF EXISTS khazana_reject_mutation()")
        op.execute("DROP FUNCTION IF EXISTS khazana_check_lot_balance()")
        op.execute("DROP FUNCTION IF EXISTS khazana_check_manifest_balance()")

    # Dropped explicitly, in reverse dependency order, for the same reason
    # the creation is explicit. drop_all would drop whatever the models say
    # today, which on an older database is the wrong set.
    op.drop_index("ix_shipments_order", table_name="shipments")
    op.drop_table("shipments")
    op.drop_index("ix_payouts_brand_status", table_name="payouts")
    op.drop_table("payouts")
    op.drop_index("ix_payments_order_status", table_name="payments")
    op.drop_table("payments")
    op.drop_table("order_lines")
    op.drop_index("ix_defects_lot", table_name="lot_defects")
    op.drop_table("lot_defects")
    op.drop_index("ix_disputes_status_created", table_name="disputes")
    op.drop_table("disputes")
    op.drop_index("ix_orders_lot", table_name="orders")
    op.drop_index("ix_orders_buyer_created", table_name="orders")
    op.drop_index("ix_orders_brand_status", table_name="orders")
    op.drop_table("orders")
    op.drop_index("ix_manifest_lot", table_name="manifest_lines")
    op.drop_table("manifest_lines")
    op.drop_index("ix_photos_lot_order", table_name="lot_photos")
    op.drop_index("ix_photos_lot_checksum", table_name="lot_photos")
    op.drop_table("lot_photos")
    op.drop_table("lot_excluded_cities")
    op.drop_index("ix_approvals_lot_created", table_name="listing_approvals")
    op.drop_table("listing_approvals")
    op.drop_index("ix_embeddings_owner", table_name="embeddings")
    op.drop_index("ix_embeddings_lot", table_name="embeddings")
    op.drop_table("embeddings")
    op.drop_index("ix_ai_outputs_prompt", table_name="ai_outputs")
    op.drop_index("ix_ai_outputs_accepted", table_name="ai_outputs")
    op.drop_table("ai_outputs")
    op.drop_index("ix_docs_brand_status", table_name="verification_documents")
    op.drop_table("verification_documents")
    op.drop_index("ix_lots_city", table_name="lots")
    op.drop_index("ix_lots_browse", table_name="lots")
    op.drop_index("ix_lots_brand_status", table_name="lots")
    op.drop_table("lots")
    op.drop_table("brand_policies")
    op.drop_index("ix_brand_members_user", table_name="brand_members")
    op.drop_table("brand_members")
    op.drop_table("brand_excluded_cities")
    op.drop_index("ix_audit_entity", table_name="audit_log")
    op.drop_index("ix_audit_brand_created", table_name="audit_log")
    op.drop_index("ix_audit_actor_created", table_name="audit_log")
    op.drop_index("ix_audit_action_created", table_name="audit_log")
    op.drop_table("audit_log")
    op.drop_index("ix_ai_spend_day", table_name="ai_spend")
    op.drop_table("ai_spend")
    op.drop_index("ix_ai_jobs_feature_status", table_name="ai_jobs")
    op.drop_index("ix_ai_jobs_entity", table_name="ai_jobs")
    op.drop_index("ix_ai_jobs_brand_created", table_name="ai_jobs")
    op.drop_table("ai_jobs")
    op.drop_index("ix_sessions_user_revoked", table_name="sessions")
    op.drop_table("sessions")
    op.drop_index("ix_reseller_status_city", table_name="reseller_profiles")
    op.drop_table("reseller_profiles")
    op.drop_index("ix_brands_status_city", table_name="brands")
    op.drop_table("brands")
    op.drop_index("ix_users_role_active", table_name="users")
    op.drop_table("users")
    op.drop_index("ix_otp_phone_created", table_name="otp_challenges")
    op.drop_table("otp_challenges")
    op.drop_index("ix_categories_parent", table_name="categories")
    op.drop_table("categories")
    # ### end Alembic commands ###
