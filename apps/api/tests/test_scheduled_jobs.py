"""Every job the production scheduler calls is an admin only endpoint that works.

The scheduler in docker-compose.prod.yml signs in as a service admin and
calls these on a timetable. Each must answer for an admin and refuse anyone
else; the route auth walk already refuses anonymous callers.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from commerce_helpers import auth

JOBS = [
    "/admin/jobs/markdowns/batch",
    "/admin/jobs/markdowns/collect",
    "/admin/jobs/expire-pools",
    "/admin/jobs/purge-ai-cache",
    "/admin/jobs/close-dispute-windows",
    "/admin/jobs/risk",
    "/admin/jobs/forecast",
]


@pytest.mark.parametrize("path", JOBS)
def test_an_admin_can_run_each_scheduled_job(client: TestClient, admin_user, path: str) -> None:  # type: ignore[no-untyped-def]
    response = client.post(path, headers=auth(admin_user))
    assert response.status_code == 200, response.text


@pytest.mark.parametrize("path", JOBS)
def test_a_brand_cannot(client: TestClient, two_brands, path: str) -> None:  # type: ignore[no-untyped-def]
    (_, owner), _ = two_brands
    assert client.post(path, headers=auth(owner)).status_code == 403
