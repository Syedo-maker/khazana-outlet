"""Every API response carries the headers that make it harder to misuse."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from khazana.config import get_settings


def test_an_ordinary_response_is_private_and_unframeable(client: TestClient) -> None:
    headers = client.get("/health").headers
    assert headers["X-Content-Type-Options"] == "nosniff"
    assert headers["X-Frame-Options"] == "DENY"
    assert headers["Referrer-Policy"] == "no-referrer"
    assert headers["Cache-Control"] == "no-store"
    assert "default-src 'none'" in headers["Content-Security-Policy"]
    assert "Strict-Transport-Security" not in headers, "HSTS only in production"


def test_errors_carry_them_too(client: TestClient) -> None:
    headers = client.get("/orders").headers
    assert headers["X-Content-Type-Options"] == "nosniff"
    assert headers["Cache-Control"] == "no-store"


def test_the_interactive_docs_keep_working(client: TestClient) -> None:
    assert "Content-Security-Policy" not in client.get("/docs").headers


def test_production_adds_hsts(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(get_settings(), "environment", "production")
    assert "max-age=31536000" in client.get("/health").headers["Strict-Transport-Security"]


def test_a_preflight_answer_is_cached_for_two_hours(client: TestClient) -> None:
    response = client.options(
        "/catalog",
        headers={
            "Origin": get_settings().web_base_url,
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "authorization",
        },
    )
    assert response.headers["Access-Control-Max-Age"] == "7200"
