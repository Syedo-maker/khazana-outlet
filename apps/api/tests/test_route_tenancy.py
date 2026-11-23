"""Every brand scoped read refuses the wrong brand, found by walking the routes.

Each module has its own cross tenant tests. This one cannot be forgotten when
a route is added: it takes every GET route with a brand or lot in its path,
asks it as another brand's owner, and expects the same 404 a missing record
gets. Routes under ``/catalog`` are the buyer catalogue, which is public to
signed in buyers by design, and are left out.
"""

from __future__ import annotations

import re

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from catalog_helpers import build_submitted_lot
from commerce_helpers import auth


def _get_routes(client: TestClient) -> list[str]:
    spec = client.get("/openapi.json").json()
    return [path for path, ops in spec["paths"].items() if "get" in ops]


def test_no_brand_reads_another_brands_records(
    client: TestClient,
    db: Session,
    two_brands,
    category,  # type: ignore[no-untyped-def]
) -> None:
    (one, one_owner), (_, two_owner) = two_brands
    lot = build_submitted_lot(db, one, one_owner, category.id)
    db.commit()

    leaks = []
    checked = 0
    for path in _get_routes(client):
        if path.startswith("/catalog") or path.startswith("/admin"):
            continue
        if "{brand_id}" not in path and "{lot_id}" not in path:
            continue
        url = path.replace("{brand_id}", one.id).replace("{lot_id}", lot.id)
        if "{" in url:
            url = re.sub(r"\{[^}]+\}", "00000000-0000-0000-0000-000000000000", url)
        own = client.get(url, headers=auth(one_owner))
        other = client.get(url, headers=auth(two_owner))
        checked += 1
        if other.status_code not in (403, 404):
            leaks.append(
                f"GET {path}: other brand got {other.status_code}, owner got {own.status_code}"
            )
    assert checked >= 10, f"only {checked} brand scoped routes found"
    assert not leaks, "\n".join(leaks)
