"""Request ids, metrics, JSON logs and error report scrubbing."""

from __future__ import annotations

import json
import logging

from fastapi.testclient import TestClient

from khazana import observability


def test_every_response_carries_a_request_id(client: TestClient) -> None:
    generated = client.get("/health").headers["X-Request-ID"]
    assert len(generated) == 32
    echoed = client.get("/health", headers={"X-Request-ID": "trace-123"}).headers
    assert echoed["X-Request-ID"] == "trace-123"
    unsafe = client.get("/health", headers={"X-Request-ID": "x" * 200}).headers
    assert unsafe["X-Request-ID"] != "x" * 200, "an oversized id is replaced, not echoed"


def test_requests_are_counted_by_route_template(client: TestClient, two_brands) -> None:  # type: ignore[no-untyped-def]
    client.get("/orders/not-a-real-order")
    body = client.get("/metrics").text
    assert 'route="/orders/{order_id}"' in body, "one series per route, not per id"
    assert "not-a-real-order" not in body
    assert "khazana_http_request_seconds_bucket" in body


def test_a_json_log_line_is_one_object_with_the_request_id() -> None:
    record = logging.LogRecord("khazana", logging.INFO, __file__, 1, "placed %s", ("ORD-1",), None)
    token = observability.request_id.set("abc123")
    try:
        line = json.loads(observability.JsonFormatter().format(record))
    finally:
        observability.request_id.reset(token)
    assert line["message"] == "placed ORD-1"
    assert line["request_id"] == "abc123"
    assert line["level"] == "info"


def test_error_reports_carry_no_personal_data() -> None:
    event = {
        "user": {"id": "u1", "ip_address": "1.2.3.4"},
        "request": {
            "method": "POST",
            "url": "https://example.pk/api/orders?phone=03001234567",
            "headers": {"Authorization": "Bearer secret"},
            "cookies": {"session": "x"},
            "data": {"delivery_phone": "03001234567"},
        },
    }
    scrubbed = observability.scrub_event(event, None)
    assert "user" not in scrubbed
    assert scrubbed["request"] == {"method": "POST", "url": "https://example.pk/api/orders"}


def test_error_reporting_is_off_without_a_dsn() -> None:
    assert observability.configure_errors(None, environment="test", release="0") is False


def test_a_broken_metrics_store_never_fails_a_request(
    client: TestClient, monkeypatch, caplog
) -> None:  # type: ignore[no-untyped-def]
    """Found on staging: after a Docker restart the metrics directory came back
    unwritable, and every request, the health check included, returned 500.
    Metrics are worth losing; the request is not."""

    class Broken:
        def labels(self, *args: object) -> Broken:
            raise PermissionError("[Errno 13] Permission denied: '/tmp/prometheus/counter_9.db'")

    monkeypatch.setattr(observability, "_METRICS_BROKEN_WARNED", False)
    monkeypatch.setattr(observability, "_REQUESTS", Broken())
    monkeypatch.setattr(observability, "_LATENCY", Broken())
    with caplog.at_level("WARNING"):
        first = client.get("/health")
        second = client.get("/health")
    assert first.status_code == 200 and second.status_code == 200
    assert caplog.text.count("metrics could not be recorded") == 1, "warned once, not per request"
