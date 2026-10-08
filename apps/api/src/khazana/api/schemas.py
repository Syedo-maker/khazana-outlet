"""Request and response models for the API surface that exists in Phase 1."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from ..models.enums import UserRole


class OtpRequestIn(BaseModel):
    phone: str = Field(min_length=10, max_length=20, examples=["03001234567"])


class OtpRequestOut(BaseModel):
    sent: bool
    # Populated only when OTP_DEV_ECHO is on, which production refuses to boot
    # with. It exists so the flow is testable before an SMS gateway exists.
    dev_code: str | None = None
    message: str


class OtpVerifyIn(BaseModel):
    phone: str
    code: str = Field(min_length=4, max_length=8)
    full_name: str | None = Field(default=None, max_length=120)
    role: UserRole = UserRole.RESELLER


class TokenPair(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"  # noqa: S105  not a secret, the OAuth scheme name
    expires_in_seconds: int


class RefreshIn(BaseModel):
    refresh_token: str


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    phone: str
    full_name: str
    role: UserRole
    email: str | None = None
    preferred_language: str
    phone_verified_at: datetime | None = None
    created_at: datetime


class MeOut(BaseModel):
    user: UserOut
    brand_ids: list[str]
    is_admin: bool


class HealthOut(BaseModel):
    status: str
    environment: str
    database: str
    ai_mode: str
    version: str
