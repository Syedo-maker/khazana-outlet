"""Every route refuses an anonymous caller, unless it is meant to be public.

A route added without the principal dependency would serve its data to anyone.
This walks every route the app registers, calls it with no credentials, and
expects a refusal. The public list is short and each entry says why.
"""

from __future__ import annotations

import re

from fastapi.testclient import TestClient

PUBLIC = {
    # Liveness for the orchestrator.
    ("GET", "/health"),
    ("GET", "/ready"),
    # Left open on purpose in Phase 1: mode, models, spend cap and switches.
    # See test_ai_endpoints.py::test_the_status_endpoint_stays_open.
    ("GET", "/ai/status"),
    # Signing in has to work before there is a session.
    ("POST", "/auth/otp/request"),
    ("POST", "/auth/otp/verify"),
    ("POST", "/auth/refresh"),
    ("POST", "/auth/logout"),
    # Provider callbacks authenticate by signature, checked in the service.
    ("POST", "/payments/webhooks/{provider}"),
    ("POST", "/shipments/webhooks/{courier}"),
    ("POST", "/whatsapp/webhooks/{provider}"),
}


def _routes(client: TestClient) -> list[tuple[str, str]]:
    """Every operation, from the OpenAPI document, which lists them all."""
    spec = client.get("/openapi.json").json()
    return [
        (method.upper(), path)
        for path, operations in spec["paths"].items()
        for method in operations
        if method in {"get", "post", "put", "patch", "delete"}
    ]


def test_every_route_refuses_an_anonymous_caller(client: TestClient) -> None:
    open_routes = []
    for method, path in _routes(client):
        if (method, path) in PUBLIC:
            continue
        url = re.sub(r"\{[^}]+\}", "00000000-0000-0000-0000-000000000000", path)
        response = client.request(method, url, json={})
        if response.status_code not in (401, 403):
            open_routes.append(f"{method} {path} -> {response.status_code}")
    assert not open_routes, "routes that answer without a session:\n" + "\n".join(open_routes)


def test_the_public_list_names_only_real_routes(client: TestClient) -> None:
    assert set(_routes(client)) >= PUBLIC, sorted(PUBLIC - set(_routes(client)))
