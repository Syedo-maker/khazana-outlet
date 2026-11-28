"""Application factory.

Phase 1 exposes authentication, health and the AI gateway status only. The
marketplace routers arrive in Phase 3, and the AI feature routers in Phase 2.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from . import __version__, observability
from .ai.gateway.limits import feature_switches
from .api import openapi as api_spec
from .api.routers import (
    admin,
    ai,
    analytics,
    assistant,
    auth,
    brands,
    catalog,
    commissions,
    forecasts,
    health,
    invites,
    logistics,
    negotiations,
    orders,
    payments,
    pools,
    redirections,
    resell_kits,
    resellers,
    review,
    search,
)
from .config import get_settings
from .core.errors import AppError, CrossTenant

logger = logging.getLogger("khazana")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    if settings.log_format == "json":
        observability.configure_logging("json", settings.log_level)
    # Refuse to start a misconfigured production deployment rather than
    # discover it from a leaked OTP in the logs.
    settings.assert_production_ready()
    observability.configure_errors(
        settings.sentry_dsn, environment=settings.environment, release=__version__
    )
    logger.info(
        "starting khazana api version=%s env=%s ai_offline=%s",
        __version__,
        settings.environment,
        settings.ai_offline,
    )
    yield
    logger.info("shutting down")


def create_app() -> FastAPI:
    settings = get_settings()

    app = FastAPI(
        title="Khazana Outlet API",
        version=__version__,
        description=(
            "AI native marketplace for brand surplus stock in Pakistan. "
            "See docs/architecture.md and docs/ai-architecture.md."
        ),
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=[settings.web_base_url],
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type"],
        # How long a browser may reuse a preflight answer. The default is ten
        # minutes; on a 300 ms connection every repeated preflight is a wasted
        # round trip. Chrome caps this at two hours. Production removes
        # preflights entirely by serving the API under the web app's origin.
        max_age=7200,
    )

    @app.middleware("http")
    async def _security_headers(request: Request, call_next: Any) -> Any:
        """Headers that make a stolen or misused response less useful.

        The API returns JSON and images, never pages, so it can refuse to be
        framed, sniffed or rendered as anything else outright. Responses are
        private by default: an order, an address or a payout must never sit in
        a shared cache. Routes that are safe to cache set their own
        Cache-Control, which is left alone. The interactive docs load their
        own scripts, so they are the one place without a strict policy.
        """
        response = await call_next(request)
        headers = response.headers
        headers.setdefault("X-Content-Type-Options", "nosniff")
        headers.setdefault("X-Frame-Options", "DENY")
        headers.setdefault("Referrer-Policy", "no-referrer")
        # same-origin, not same-site: in production the API is on the web
        # app's own origin, and the web app reads it only through fetch,
        # which this header does not restrict. Tightened after the OWASP ZAP
        # baseline scan.
        headers.setdefault("Cross-Origin-Resource-Policy", "same-origin")
        headers.setdefault("Cache-Control", "no-store")
        if not request.url.path.startswith(("/docs", "/redoc", "/openapi.json")):
            headers.setdefault(
                "Content-Security-Policy", "default-src 'none'; frame-ancestors 'none'"
            )
        if settings.is_production:
            headers.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
        return response

    @app.exception_handler(AppError)
    async def _app_error_handler(request: Request, exc: AppError) -> JSONResponse:
        # A tenant boundary breach is logged loudly and answered as a 404.
        if isinstance(exc, CrossTenant):
            logger.warning(
                "cross tenant access attempt path=%s principal=%s",
                request.url.path,
                getattr(request.state, "principal", None),
            )
        return JSONResponse(
            status_code=exc.status_code,
            content={"code": exc.code, "message": exc.message},
        )

    @app.exception_handler(Exception)
    async def _unhandled(request: Request, exc: Exception) -> JSONResponse:
        """A bug reached the top. The person gets a plain sentence, the
        operator gets an email, and the details stay in the log."""
        from starlette.concurrency import run_in_threadpool

        from .services import alert_service

        request_id = observability.request_id.get()
        logger.error(
            "unhandled error path=%s request_id=%s",
            request.url.path,
            request_id,
            exc_info=exc,
        )
        await run_in_threadpool(
            alert_service.raise_alert_now,
            "server-error",
            "The API returned a server error",
            f"{request.method} {request.url.path}\nRequest id: {request_id}\n"
            f"Error type: {type(exc).__name__}\nThe traceback is in the api log.",
            cooldown_minutes=60,
        )
        return JSONResponse(
            status_code=500,
            content={
                "code": "internal_error",
                "message": "Something went wrong on our side. It has been reported.",
            },
        )

    app.include_router(health.router)
    app.include_router(auth.router)
    app.include_router(invites.router)
    app.include_router(ai.router)
    app.include_router(assistant.router)
    app.include_router(brands.router)
    # Before catalog, whose /catalog/{lot_id} would otherwise match these paths.
    app.include_router(search.router)
    app.include_router(catalog.router)
    app.include_router(orders.router)
    app.include_router(payments.router)
    app.include_router(commissions.router)
    app.include_router(resell_kits.router)
    app.include_router(pools.router)
    app.include_router(negotiations.router)
    app.include_router(forecasts.router)
    app.include_router(redirections.router)
    app.include_router(review.router)
    app.include_router(analytics.router)
    app.include_router(logistics.router)
    app.include_router(resellers.router)
    app.include_router(admin.router)

    @app.get(
        "/ai/status",
        tags=["ops"],
        operation_id="ops_ai_status",
        summary="AI mode, routed models, spend cap and feature switches",
    )
    def ai_status() -> dict[str, object]:
        """What the AI layer is doing right now.

        Exposed from Phase 1 because a platform whose AI spend and kill
        switches are invisible is a platform that will surprise you with an
        invoice.
        """
        return {
            "mode": "offline" if settings.ai_offline else "live",
            "default_model": settings.ai_model_default,
            "bulk_model": settings.ai_model_bulk,
            "daily_limit_usd": settings.ai_daily_spend_limit_usd,
            "features": feature_switches(),
        }

    # Request ids, request metrics and the /metrics route.
    observability.install(app)
    # Authentication, the error shape and tag descriptions, added to the spec
    # FastAPI generates. See api/openapi.py.
    api_spec.install(app)
    return app


app = create_app()
