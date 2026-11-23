"""The migrations create every index the models declare.

The tests build their schema with ``create_all`` from the models, so a model
index that no migration creates passes every test and is missing in every real
database. This applies the migrations to a scratch SQLite file and compares
its indexes with the models'. The PostgreSQL drift check in CI covers columns
and types; this covers the indexes on every run of the suite.
"""

from __future__ import annotations

import os
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect

from khazana.config import get_settings
from khazana.models import Base

API = Path(__file__).resolve().parent.parent


def test_every_model_index_is_created_by_a_migration(tmp_path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    url = f"sqlite:///{tmp_path / 'migrated.db'}"
    monkeypatch.setenv("DATABASE_URL", url)
    get_settings.cache_clear()
    try:
        config = Config(str(API / "alembic.ini"))
        config.set_main_option("script_location", str(API / "alembic"))
        cwd = os.getcwd()
        os.chdir(API)
        try:
            command.upgrade(config, "head")
        finally:
            os.chdir(cwd)
    finally:
        get_settings.cache_clear()

    inspector = inspect(create_engine(url))
    missing = []
    for table in Base.metadata.sorted_tables:
        have = {index["name"] for index in inspector.get_indexes(table.name)}
        for index in table.indexes:
            if index.name and index.name not in have:
                missing.append(f"{table.name}.{index.name}")
    assert not missing, f"indexes declared on the models but created by no migration: {missing}"
