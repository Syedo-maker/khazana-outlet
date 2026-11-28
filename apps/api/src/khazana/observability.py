"""Logs, metrics and error reports, for running the API in production.

Three things, each switched on by configuration and silent without it:

- **Structured logs.** With ``LOG_FORMAT=json`` every log line is one JSON
  object with a timestamp, level, logger, message and the request id, ready
  for any log aggregator to index. Development keeps plain text.
- **Request ids and metrics.** Every request gets an ``X-Request-ID`` (the
  caller's, if it sent a sane one) that appears in its log lines and in the
  response. Request counts and latency by route are exported in Prometheus
  format at ``/metrics``, which the production proxy does not expose to the
  internet.
- **Error reports.** With ``SENTRY_DSN`` set, unhandled exceptions go to that
  service. Any Sentry compatible one works, including a self hosted GlitchTip.
  No personal data is sent: no headers, no bodies, no user identity.
"""

from __future__ import annotations

import json
import logging
import os
import re
import time
import uuid
from collections.abc import Awaitable, Callable
from contextvars import ContextVar
from typing import Any

from fastapi import FastAPI, Request, Response

request_id: ContextVar[str] = ContextVar("request_id", default="-")

_SAFE_ID = re.compile(r"^[A-Za-z0-9._-]{1,64}$")


class JsonFormatter(logging.Formatter):
    """One JSON object per line."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "time": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname.lower(),
            "logger": record.name,
            "message": record.getMessage(),
            "request_id": request_id.get(),
        }
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False)


def configure_logging(fmt: str, level: str = "INFO") -> None:
    """Send every logger, uvicorn's included, through one handler."""
    handler = logging.StreamHandler()
    if fmt == "json":
        handler.setFormatter(JsonFormatter())
    else:
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(level.upper())
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        logging.getLogger(name).handlers = []
        logging.getLogger(name).propagate = True


def configure_errors(dsn: str | None, *, environment: str, release: str) -> bool:
    """Start error reporting if a DSN is configured. Returns whether it did."""
    if not dsn:
        return False
    import sentry_sdk

    sentry_sdk.init(
        dsn=dsn,
        environment=environment,
        release=release,
        traces_sample_rate=0.0,
        before_send=scrub_event,
    )
    return True


def scrub_event(event: Any, hint: Any) -> Any:
    """Strip anything that could identify a person before an event leaves.

    Done here rather than trusted to the library's defaults, which have
    changed between major versions: no user, no headers or cookies, no request
    body and no query string. What is left is the method, the path and the
    stack trace, which is what a developer needs.
    """
    event.pop("user", None)
    request = event.get("request")
    if isinstance(request, dict):
        event["request"] = {
            "method": request.get("method"),
            "url": str(request.get("url", "")).split("?", 1)[0],
        }
    return event


# ------------------------------------------------------------------ metrics


def _registry() -> Any:
    """The registry to export, aware of several worker processes.

    With ``PROMETHEUS_MULTIPROC_DIR`` set, each uvicorn worker writes its
    counts to that directory and ``/metrics`` adds them up, so a scrape sees
    the whole container, not whichever worker answered.
    """
    from prometheus_client import REGISTRY, CollectorRegistry, multiprocess

    if os.environ.get("PROMETHEUS_MULTIPROC_DIR"):
        registry = CollectorRegistry()
        multiprocess.MultiProcessCollector(registry)  # type: ignore[no-untyped-call]
        return registry
    return REGISTRY


def _metrics() -> tuple[Any, Any]:
    from prometheus_client import Counter, Histogram

    global _REQUESTS, _LATENCY
    if _REQUESTS is None:
        _REQUESTS = Counter(
            "khazana_http_requests_total",
            "HTTP requests by route template, method and status class.",
            ["route", "method", "status"],
        )
        _LATENCY = Histogram(
            "khazana_http_request_seconds",
            "Time to answer an HTTP request, by route template.",
            ["route"],
            buckets=(0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10),
        )
    return _REQUESTS, _LATENCY


_REQUESTS: Any = None
_LATENCY: Any = None
_METRICS_BROKEN_WARNED = False


def _record(route: str, method: str, status: int, elapsed: float) -> None:
    """Count one request. Never raises.

    A metrics store that cannot be written, as happened on staging when the
    multiprocess directory came back unwritable after a Docker restart, must
    not turn every request into a 500. It is reported once and skipped.
    """
    global _METRICS_BROKEN_WARNED
    try:
        _REQUESTS.labels(route, method, f"{status // 100}xx").inc()
        _LATENCY.labels(route).observe(elapsed)
    except Exception as exc:
        if not _METRICS_BROKEN_WARNED:
            _METRICS_BROKEN_WARNED = True
            logging.getLogger("khazana.metrics").warning(
                "metrics could not be recorded, requests continue without them: %s", exc
            )


def install(app: FastAPI) -> None:
    """Add the request id and metrics middleware, and the /metrics route."""
    _metrics()
    logger = logging.getLogger("khazana.request")

    @app.middleware("http")
    async def _observe(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        incoming = request.headers.get("x-request-id", "")
        token = request_id.set(incoming if _SAFE_ID.match(incoming) else uuid.uuid4().hex)
        started = time.perf_counter()
        status = 500
        try:
            response = await call_next(request)
            status = response.status_code
            response.headers["X-Request-ID"] = request_id.get()
            return response
        finally:
            elapsed = time.perf_counter() - started
            # The route template, never the raw path: /orders/{order_id} is one
            # series, where raw paths would be one per order.
            route = getattr(request.scope.get("route"), "path", "unmatched")
            if route != "/metrics":
                _record(route, request.method, status, elapsed)
                logger.info("%s %s %s %.0fms", request.method, route, status, elapsed * 1000)
            request_id.reset(token)

    @app.get("/metrics", include_in_schema=False)
    def metrics() -> Response:
        """Prometheus format. Not routed by the production proxy."""
        from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

        return Response(generate_latest(_registry()), media_type=CONTENT_TYPE_LATEST)
