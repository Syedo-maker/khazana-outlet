"""Application settings, read from the environment.

Everything configurable lives here. No module reads ``os.environ`` directly,
so the full configuration surface of the platform is one file you can audit.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(".env", "../../.env"),
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # ---------- Core ----------
    environment: Literal["development", "test", "staging", "production"] = "development"
    # Deliberately obvious. assert_production_ready refuses to boot with it.
    secret_key: str = "insecure-development-key-change-me"  # noqa: S105
    api_base_url: str = "http://localhost:8000"
    web_base_url: str = "http://localhost:3000"

    # ---------- Database ----------
    database_url: str = "postgresql+psycopg://khazana:khazana@localhost:5432/khazana"

    # ---------- Redis ----------
    redis_url: str = "redis://localhost:6379/0"

    # ---------- Auth ----------
    access_token_ttl_minutes: int = 60
    refresh_token_ttl_days: int = 30
    otp_ttl_seconds: int = 300
    otp_max_attempts: int = 5
    otp_resend_cooldown_seconds: int = 60
    otp_dev_echo: bool = True

    # ---------- Anthropic ----------
    anthropic_api_key: str | None = None
    ai_model_default: str = "claude-opus-5-5"
    ai_model_bulk: str = "claude-haiku-4-5"
    ai_daily_spend_limit_usd: float = 5.00
    ai_brand_monthly_spend_limit_usd: float = 20.00
    ai_offline: bool = True

    # ---------- Storage ----------
    storage_backend: Literal["local", "s3"] = "local"
    storage_local_path: str = "./uploads"
    s3_endpoint: str | None = None
    s3_bucket: str | None = None
    s3_access_key: str | None = None
    s3_secret_key: str | None = None

    # ---------- Embeddings ----------
    embedding_model: str = "siglip-base-patch16-224"
    embedding_dim: int = 768
    embedding_service_url: str | None = None

    # ---------- Business defaults ----------
    # Starting values for a new brand's policy row. Once a brand exists, its
    # own policy row is authoritative and these are never consulted again.
    default_commission_percent: float = Field(default=15.0, ge=0, le=50)
    default_min_lot_value_pkr: int = 25_000
    dispute_window_days: int = 3

    @property
    def is_production(self) -> bool:
        return self.environment == "production"

    @field_validator("secret_key")
    @classmethod
    def _reject_default_secret_in_production(cls, value: str, info: object) -> str:
        # The environment field may not be parsed yet, so this check is also
        # made at startup in main.py where the full settings object exists.
        return value

    def assert_production_ready(self) -> None:
        """Fail fast at startup rather than leak an insecure deployment.

        Called from the application factory. These three mistakes are the ones
        that actually happen: shipping the sample secret, leaving the OTP code
        printed in the logs, and deploying with no Anthropic key so every AI
        feature silently falls back to fixtures.
        """
        if not self.is_production:
            return
        problems: list[str] = []
        if "change-me" in self.secret_key or "insecure" in self.secret_key:
            problems.append("SECRET_KEY is still the example value")
        if len(self.secret_key) < 32:
            problems.append("SECRET_KEY is shorter than 32 characters")
        if self.otp_dev_echo:
            problems.append("OTP_DEV_ECHO must be false in production")
        if self.ai_offline:
            problems.append("AI_OFFLINE must be false in production")
        if not self.anthropic_api_key:
            problems.append("ANTHROPIC_API_KEY is not set")
        if self.database_url.startswith("sqlite"):
            problems.append("DATABASE_URL points at SQLite")
        if problems:
            raise RuntimeError("Unsafe production configuration: " + "; ".join(problems))


@lru_cache
def get_settings() -> Settings:
    return Settings()
