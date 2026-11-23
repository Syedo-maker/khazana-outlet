"""List endpoints cost the same number of queries however many brands they show.

The load test on a 500 lot catalogue found the catalogue loading each lot's
brand with its own query: 20 lots from 20 brands was 20 extra round trips on
the page every reseller opens first. These tests count the statements a list
request runs with lots from two brands and from many, and fail if the count
grows with the number of brands, which is what an N plus 1 query looks like.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event
from sqlalchemy.orm import Session

from commerce_helpers import auth, live_lot, make_courier, make_reseller
from conftest import make_brand


@contextmanager
def _counting(db: Session) -> Iterator[list[str]]:
    statements: list[str] = []
    engine = db.get_bind()

    def _record(conn, cursor, statement, params, context, executemany):  # type: ignore[no-untyped-def]
        statements.append(statement)

    event.listen(engine, "before_cursor_execute", _record)
    try:
        yield statements
    finally:
        event.remove(engine, "before_cursor_execute", _record)


def _add_brands(db: Session, category, first: int, last: int) -> None:  # type: ignore[no-untyped-def]
    """Brands numbered first to last, each with two live lots."""
    for number in range(first, last):
        brand, owner = make_brand(
            db,
            name=f"Brand {number} (sample)",
            slug=f"brand-{number}",
            owner_phone=f"0333{number:07d}",
        )
        for offset in range(2):
            live_lot(db, brand, owner, category.id, offset=number * 10 + offset)


def _count(client: TestClient, db: Session, url: str, headers: dict[str, str]) -> int:
    client.get(url, headers=headers)  # warm anything cached per process
    with _counting(db) as statements:
        response = client.get(url, headers=headers)
    assert response.status_code == 200, response.text
    return len(statements)


@pytest.mark.parametrize(
    "url",
    ["/catalog?limit=24", "/catalog/search?limit=24", "/catalog/recommendations?limit=12"],
)
def test_list_queries_do_not_grow_with_the_number_of_brands(
    client: TestClient, db: Session, category, url: str
) -> None:  # type: ignore[no-untyped-def]
    buyer = make_reseller(db)
    make_courier(db)
    _add_brands(db, category, 0, 2)
    few = _count(client, db, url, auth(buyer))
    _add_brands(db, category, 2, 9)
    many = _count(client, db, url, auth(buyer))
    assert many <= few, f"{url}: {few} queries with 2 brands, {many} with 9"


def test_the_admin_listing_queue_does_not_grow_with_its_length(
    client: TestClient, db: Session, category, admin_user
) -> None:  # type: ignore[no-untyped-def]
    make_courier(db)
    _add_brands(db, category, 0, 2)
    few = _count(client, db, "/admin/listings", auth(admin_user))
    _add_brands(db, category, 2, 9)
    many = _count(client, db, "/admin/listings", auth(admin_user))
    assert many <= few, f"/admin/listings: {few} queries for 4 lots, {many} for 18"


def test_a_brands_order_list_does_not_grow_with_its_length(
    client: TestClient, db: Session, two_brands, category
) -> None:  # type: ignore[no-untyped-def]
    from commerce_helpers import whole_order

    (brand, owner), _ = two_brands
    make_courier(db)

    def orders(first: int, last: int) -> None:
        for number in range(first, last):
            lot = live_lot(db, brand, owner, category.id, offset=100 + number)
            whole_order(db, make_reseller(db, phone=f"0345{number:07d}"), lot)

    orders(0, 2)
    few = _count(client, db, "/orders", auth(owner))
    orders(2, 8)
    many = _count(client, db, "/orders", auth(owner))
    assert many <= few, f"/orders: {few} queries for 2 orders, {many} for 8"
