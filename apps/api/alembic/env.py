"""Alembic environment.

The database URL comes from the application settings, so there is exactly one
place that knows how to reach the database.
"""

from __future__ import annotations

from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from khazana.config import get_settings
from khazana.models import Base

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

config.set_main_option("sqlalchemy.url", get_settings().database_url)

target_metadata = Base.metadata


# Objects that exist in the database on purpose and cannot be expressed in the
# model metadata. Without this, autogenerate proposes dropping them on every
# run, and a diff full of proposals nobody wants is a diff nobody reads.
UNMANAGED_INDEXES = {"ix_embeddings_vector_cosine"}


def include_object(obj, name, type_, reflected, compare_to):
    """Keep the hand written pgvector index out of autogenerate.

    It is an HNSW index using vector_cosine_ops, created by raw SQL in
    migration 0001 because SQLAlchemy has no way to declare the operator
    class. Autogenerate finds it in the database, does not find it in the
    metadata, and concludes it should be dropped.
    """
    return not (type_ == "index" and name in UNMANAGED_INDEXES)


def render_item(type_, obj, autogen_context):
    """Render the two custom column types the way a migration needs them.

    Autogenerate writes the Python type it finds on the model, which is wrong
    for both of ours and silently so until the migration runs.

    `EnumText` is a TypeDecorator whose impl is `String`. Rendered as itself it
    produces `EnumText(length=32)`, which cannot be constructed because the
    enum class is a required argument, and which in any case describes nothing
    the database sees: at DDL level the column is `VARCHAR(32)`. So it renders
    as `sa.String`.

    `Vector` has to be referenced rather than resolved, because it is a real
    pgvector column on PostgreSQL and JSON on SQLite. Naming either concrete
    type would break the other dialect, so the migration keeps the decorator
    and lets it decide at run time.

    Without this, freezing the baseline on 2026-10-14 produced a migration that
    failed on its first table.
    """
    if type_ == "type":
        from khazana.models.base import EnumText, Vector

        if isinstance(obj, EnumText):
            autogen_context.imports.add("import sqlalchemy as sa")
            return f"sa.String(length={obj.impl_instance.length})"
        if isinstance(obj, Vector):
            autogen_context.imports.add("import khazana.models.base")
            return f"khazana.models.base.Vector(dim={obj.dim})"
    # False means "use the default rendering".
    return False


def run_migrations_offline() -> None:
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
        compare_server_default=True,
        render_item=render_item,
        include_object=include_object,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
            compare_server_default=True,
            render_item=render_item,
            include_object=include_object,
            # Needed for SQLite, harmless on PostgreSQL, and it means an
            # ALTER on a constraint does not fail silently in tests.
            render_as_batch=connection.dialect.name == "sqlite",
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
