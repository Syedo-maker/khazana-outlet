"""Health and readiness.

Two endpoints on purpose. ``/health`` answers "is the process alive" and must
never touch the database, because a readiness probe that depends on the
database takes the whole service out of the load balancer during a brief
database blip. ``/ready`` answers "can it serve traffic" and does check.
"""

from __future__ import annotations

from fastapi import APIRouter, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy import select, text

from ... import __version__
from ...config import get_settings
from ...models import User
from ...models.enums import UserRole
from ..deps import Db
from ..schemas import HealthOut

router = APIRouter(tags=["ops"])


@router.get(
    "/health",
    operation_id="ops_health",
    summary="Liveness, without touching the database",
    response_model=HealthOut,
)
def health() -> HealthOut:
    settings = get_settings()
    return HealthOut(
        status="ok",
        environment=settings.environment,
        database="not checked",
        ai_mode="offline" if settings.ai_offline else "live",
        version=__version__,
    )


@router.get(
    "/ready",
    operation_id="ops_ready",
    summary="Readiness, including a database check",
)
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


class DemoAccount(BaseModel):
    role: UserRole
    phone: str
    name: str


class DemoOut(BaseModel):
    enabled: bool
    accounts: list[DemoAccount]


@router.get(
    "/demo",
    operation_id="ops_demo",
    summary="Whether this is a public demo, and its sample accounts",
    response_model=DemoOut,
)
def demo(db: Db) -> DemoOut:
    """The sample accounts the login page offers on a demo, one per role.

    Empty unless DEMO_MODE is on, so a real deployment never lists accounts.
    """
    if not get_settings().demo_mode:
        return DemoOut(enabled=False, accounts=[])
    accounts = []
    for role in (UserRole.RESELLER, UserRole.BRAND, UserRole.ADMIN):
        user = db.scalars(
            select(User).where(User.role == role, User.is_active.is_(True)).order_by(User.phone)
        ).first()
        if user is not None:
            accounts.append(DemoAccount(role=role, phone=user.phone, name=user.full_name))
    return DemoOut(enabled=True, accounts=accounts)
