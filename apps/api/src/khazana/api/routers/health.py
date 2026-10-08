"""Health and readiness.

Two endpoints on purpose. ``/health`` answers "is the process alive" and must
never touch the database, because a readiness probe that depends on the
database takes the whole service out of the load balancer during a brief
database blip. ``/ready`` answers "can it serve traffic" and does check.
"""

from __future__ import annotations

from fastapi import APIRouter, status
from fastapi.responses import JSONResponse
from sqlalchemy import text

from ... import __version__
from ...config import get_settings
from ..deps import Db
from ..schemas import HealthOut

router = APIRouter(tags=["ops"])


@router.get("/health", response_model=HealthOut)
def health() -> HealthOut:
    settings = get_settings()
    return HealthOut(
        status="ok",
        environment=settings.environment,
        database="not checked",
        ai_mode="offline" if settings.ai_offline else "live",
        version=__version__,
    )


@router.get("/ready")
def ready(db: Db) -> JSONResponse:
    settings = get_settings()
    try:
        db.execute(text("SELECT 1"))
        database = "ok"
        code = status.HTTP_200_OK
    except Exception as exc:
        # The reason is logged, not returned. A readiness endpoint that prints
        # connection strings is an information leak.
        database = "unavailable"
        code = status.HTTP_503_SERVICE_UNAVAILABLE
        import logging

        logging.getLogger(__name__).error("readiness check failed: %s", exc)

    return JSONResponse(
        status_code=code,
        content={
            "status": "ok" if code == status.HTTP_200_OK else "degraded",
            "environment": settings.environment,
            "database": database,
            "ai_mode": "offline" if settings.ai_offline else "live",
            "version": __version__,
        },
    )
