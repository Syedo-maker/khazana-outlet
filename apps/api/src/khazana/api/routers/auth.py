"""Authentication endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Request, status

from ...config import get_settings
from ...core.errors import AppError
from ...models.enums import OtpPurpose
from ...services import auth_service
from ..deps import CurrentPrincipal, Db, client_ip
from ..schemas import (
    MeOut,
    OtpRequestIn,
    OtpRequestOut,
    OtpVerifyIn,
    RefreshIn,
    TokenPair,
    UserOut,
)

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/otp/request", response_model=OtpRequestOut)
def request_otp(payload: OtpRequestIn, db: Db) -> OtpRequestOut:
    settings = get_settings()
    try:
        code = auth_service.request_otp(db, payload.phone, OtpPurpose.LOGIN)
    except AppError as exc:
        raise exc.as_http() from exc

    return OtpRequestOut(
        sent=True,
        dev_code=code,
        message=(
            f"Code sent. It expires in {settings.otp_ttl_seconds // 60} minutes."
            if not settings.otp_dev_echo
            else "Development mode: the code is in this response and in the log."
        ),
    )


@router.post("/otp/verify", response_model=TokenPair)
def verify_otp(payload: OtpVerifyIn, request: Request, db: Db) -> TokenPair:
    settings = get_settings()
    try:
        _user, access, refresh = auth_service.verify_otp_and_login(
            db,
            payload.phone,
            payload.code,
            full_name=payload.full_name,
            role=payload.role,
            user_agent=request.headers.get("user-agent"),
            ip=client_ip(request),
        )
    except AppError as exc:
        raise exc.as_http() from exc

    return TokenPair(
        access_token=access,
        refresh_token=refresh,
        expires_in_seconds=settings.access_token_ttl_minutes * 60,
    )


@router.post("/refresh", response_model=TokenPair)
def refresh(payload: RefreshIn, request: Request, db: Db) -> TokenPair:
    settings = get_settings()
    try:
        access, new_refresh = auth_service.refresh_session(
            db,
            payload.refresh_token,
            user_agent=request.headers.get("user-agent"),
            ip=client_ip(request),
        )
    except AppError as exc:
        raise exc.as_http() from exc

    return TokenPair(
        access_token=access,
        refresh_token=new_refresh,
        expires_in_seconds=settings.access_token_ttl_minutes * 60,
    )


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(principal: CurrentPrincipal, db: Db) -> None:
    """Revoke every session for this user, not only the current one.

    Logging out of one device while a stolen token still works elsewhere is
    not logging out.
    """
    auth_service.revoke_all_sessions(db, principal.user_id)


@router.get("/me", response_model=MeOut)
def me(principal: CurrentPrincipal, db: Db) -> MeOut:
    from ...models import User

    user = db.get(User, principal.user_id)
    if user is None:  # pragma: no cover, the dependency already proved it exists
        from ...core.errors import NotFound

        raise NotFound("user not found").as_http()

    return MeOut(
        user=UserOut.model_validate(user),
        brand_ids=principal.brand_ids,
        is_admin=principal.is_admin,
    )
