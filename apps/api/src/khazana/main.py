"""Application factory.

Phase 1 exposes authentication, health and the AI gateway status only. The
marketplace routers arrive in Phase 3, and the AI feature routers in Phase 2.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from . import __version__
from .ai.gateway.limits import feature_switches
from .api.routers import auth, health
from .config import get_settings
from .core.errors import AppError, CrossTenant

logger = logging.getLogger("khazana")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    # Refuse to start a misconfigured production deployment rather than
    # discover it from a leaked OTP in the logs.
    settings.assert_production_ready()
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
        allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type"],
    )

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

    app.include_router(health.router)
    app.include_router(auth.router)

    @app.get("/ai/status", tags=["ops"])
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

    return app


app = create_app()
