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
from ...ai import availability
from ...config import get_settings
from ...legal import TERMS_VERSION
from ...models import User
from ...models.enums import UserRole
from ...services import auth_service
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


class AiFeaturesOut(BaseModel):
    enabled: bool
    # False once today's spend has reached the cap: every AI feature then
    # shows its manual path until the next day.
    available_today: bool
    daily_cap_usd: float


class FeaturesOut(BaseModel):
    """What this deployment has switched on. The pilot runs with no paid
    provider, so most of these are off, and the interface says so instead of
    failing."""

    sms_login: bool
    # Sign in only with a link an admin made.
    invite_only: bool
    # Whether the login page can ask for a code at all: sent by SMS, or shown
    # on screen in development and on a demo.
    login_codes: bool
    whatsapp: bool
    speech_to_text: bool
    visual_search: bool
    ai: AiFeaturesOut
    settlement_default: str
    terms_version: str
    demo: bool


@router.get(
    "/features",
    operation_id="ops_features",
    summary="Which optional features this deployment has switched on",
    response_model=FeaturesOut,
)
def features(db: Db) -> FeaturesOut:
    settings = get_settings()
    sms = settings.sms_login_enabled
    return FeaturesOut(
        sms_login=sms,
        invite_only=not sms,
        login_codes=auth_service.sms_codes_available(),
        whatsapp=settings.whatsapp_enabled,
        speech_to_text=settings.speech_to_text_enabled,
        visual_search=settings.visual_search_enabled,
        ai=AiFeaturesOut(
            enabled=settings.ai_enabled,
            available_today=availability.available_today(db),
            daily_cap_usd=settings.ai_daily_spend_limit_usd,
        ),
        settlement_default=settings.default_settlement_mode,
        terms_version=TERMS_VERSION,
        demo=settings.demo_mode,
    )
