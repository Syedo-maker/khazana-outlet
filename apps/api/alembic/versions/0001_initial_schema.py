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
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

from khazana.models import BRAND_SCOPED_TABLES, Base

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

    Base.metadata.create_all(bind)

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

    Base.metadata.drop_all(bind)
