"""Columns the tenancy filter reads are indexed.

Every query on a brand scoped table filters by ``brand_id``, and so do the row
level security policies. PostgreSQL does not index a foreign key by itself, so
a brand scoped table added without an index on ``brand_id`` gets a sequential
scan per tenant query. This catches that when the table is added.
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import PrimaryKeyConstraint, UniqueConstraint

from khazana.models import BRAND_SCOPED_TABLES, Base, as_utc


def _leading_columns(table) -> set[str]:  # type: ignore[no-untyped-def]
    leading = {next(iter(index.columns)).name for index in table.indexes if index.columns}
    for constraint in table.constraints:
        if isinstance(constraint, UniqueConstraint | PrimaryKeyConstraint) and constraint.columns:
            leading.add(next(iter(constraint.columns)).name)
    return leading


def test_every_brand_scoped_table_is_indexed_on_brand_id() -> None:
    missing = [
        name
        for name in BRAND_SCOPED_TABLES
        if "brand_id" not in _leading_columns(Base.metadata.tables[name])
    ]
    assert not missing, f"brand scoped tables without an index on brand_id: {missing}"


def test_as_utc_makes_a_naive_time_aware_and_leaves_an_aware_one_alone() -> None:
    naive = datetime(2026, 11, 20, 9, 0)
    aware = datetime(2026, 11, 20, 9, 0, tzinfo=UTC)
    assert as_utc(naive) == aware
    assert as_utc(aware) is aware
