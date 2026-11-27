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

    # ---------- Operations ----------
    # json in staging and production, so a log aggregator can index each line.
    log_format: Literal["text", "json"] = "text"
    log_level: str = "INFO"
    # Error reports go here when set: Sentry, or a self hosted GlitchTip.
    sentry_dsn: str | None = None
    # A public demonstration: only the sample accounts can sign in, the login
    # page offers them, every page says it is a demo, and the data is reseeded
    # every night. Production refuses to start with it on.
    demo_mode: bool = False

    # ---------- Database ----------
    # 55432 to match .env.example and what compose publishes, not 5432.
    # Inside the containers compose sets this to db:5432 and none of it
    # applies. It matters for a native run: a developer with no .env would
    # otherwise reach whatever else is listening on 5432, which on at least
    # one development machine is a separate PostgreSQL install holding none of
    # this data and looking identical.
    database_url: str = "postgresql+psycopg://khazana:khazana@localhost:55432/khazana"

    # ---------- Redis ----------
    redis_url: str = "redis://localhost:56379/0"

    # ---------- Auth ----------
    access_token_ttl_minutes: int = 60
    refresh_token_ttl_days: int = 30
    otp_ttl_seconds: int = 300
    otp_max_attempts: int = 5
    otp_resend_cooldown_seconds: int = 60
    otp_dev_echo: bool = True
    # Codes one network address may request in an hour, across every phone
    # number. Each code is an SMS someone pays for, so without this one script
    # can send thousands to numbers it does not own.
    otp_ip_hourly_limit: int = Field(default=20, ge=1)
    # A rotated refresh token presented again after this many seconds is
    # treated as stolen and signs the user out everywhere. Inside it, it is
    # most likely two tabs refreshing at once, and only that request fails.
    refresh_reuse_grace_seconds: int = Field(default=60, ge=0)
    # How many proxies in front of the API append to X-Forwarded-For. Zero
    # means the header is ignored, because a client can write anything in it.
    # Behind the production Caddy proxy it is 1.
    trusted_proxy_count: int = Field(default=0, ge=0, le=5)

    # ---------- Anthropic ----------
    anthropic_api_key: str | None = None
    ai_model_default: str = "claude-opus-5-5"
    ai_model_bulk: str = "claude-haiku-4-5"
    # The whole platform's model spend in one day (UTC). When it is
    # reached every AI feature falls back to its manual path until midnight;
    # nothing errors. One dollar is the pilot's budget.
    ai_daily_spend_limit_usd: float = Field(default=1.00, ge=0)
    ai_brand_monthly_spend_limit_usd: float = 20.00
    ai_offline: bool = True
    # Off: no model is called at all, and every AI feature shows its manual
    # path. For running with no Anthropic key.
    ai_enabled: bool = True

    # ---------- Assistant ----------
    # Each buyer message costs two model calls, so a per user daily cap is the
    # control that keeps one chatty account from spending the whole budget.
    assistant_daily_message_limit: int = Field(default=40, ge=1)
    # How many earlier messages the model sees. Older turns are dropped, not
    # summarised, so the cost of a long conversation stays flat.
    assistant_history_messages: int = Field(default=6, ge=0, le=20)
    # Below this, a voice note transcript is not trusted and the buyer is asked
    # to type instead. A wrong lot code or quantity costs more than a retype.
    voice_min_confidence: float = Field(default=0.6, ge=0, le=1)
    # Longest voice note sent for transcription. A buyer's question fits in a
    # minute; transcription is billed per minute, so the cap is a cost control.
    voice_max_seconds: int = Field(default=120, ge=10, le=600)
    # A WhatsApp message after this long a silence starts a new conversation,
    # so yesterday's search does not colour today's question.
    whatsapp_conversation_idle_hours: int = Field(default=12, ge=1)

    # ---------- Committee pools ----------
    pool_min_members: int = Field(default=3, ge=2, le=10)
    pool_max_members: int = Field(default=4, ge=2, le=10)
    pool_open_days: int = Field(default=7, ge=1, le=60)

    # ---------- Risk review ----------
    # A score at or above this opens a case for a person to review.
    risk_case_threshold: int = Field(default=40, ge=1, le=100)

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

    # ---------- Pilot switches ----------
    # Who collects the buyer's money on a new brand's orders. "direct": the
    # buyer pays the brand's own courier on delivery and the platform invoices
    # its commission monthly; the platform never holds money. "platform": the
    # platform holds payment until the buyer confirms. Existing brands keep
    # their own policy row.
    default_settlement_mode: Literal["platform", "direct"] = "direct"
    # Days a brand has to pay its monthly commission invoice.
    commission_invoice_due_days: int = Field(default=15, ge=1, le=90)
    # SMS login codes need a paid SMS gateway. Off: people sign in with a
    # single use link an admin creates and sends them by hand.
    sms_login_enabled: bool = False
    # How long an invite or sign in link works for.
    invite_ttl_hours: int = Field(default=72, ge=1, le=720)
    # Each of these needs a paid provider. Off: the feature explains itself in
    # the interface instead of failing.
    whatsapp_enabled: bool = False
    speech_to_text_enabled: bool = False
    visual_search_enabled: bool = False

    # ---------- Alerts ----------
    # Plain email to one address through any SMTP server. Unset: alerts are
    # logged only. See docs/deployment.md for a free provider.
    alert_email_to: str | None = None
    alert_email_from: str | None = None
    smtp_host: str | None = None
    smtp_port: int = Field(default=587, ge=1, le=65535)
    smtp_username: str | None = None
    smtp_password: str | None = None
    # STARTTLS on 587. Set false and use port 465 for implicit TLS instead.
    smtp_starttls: bool = True
    # One alert of a kind per this many minutes, so a failing job every
    # half hour is one email, not forty eight.
    alert_cooldown_minutes: int = Field(default=180, ge=1)

    # ---------- Payments ----------
    # Shown to buyers paying by bank transfer. The defaults are obviously fake,
    # and production refuses to start with them.
    bank_account_title: str = "Khazana Outlet Sandbox"
    bank_account_iban: str = "PK00SANDBOX0000000000000"

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
        if self.ai_enabled:
            # With AI deliberately switched off there is no key to check and
            # no fixtures can be served by mistake: every feature is manual.
            if self.ai_offline:
                problems.append("AI_OFFLINE must be false in production")
            if not self.anthropic_api_key:
                problems.append("ANTHROPIC_API_KEY is not set; set it, or AI_ENABLED=false")
        if self.database_url.startswith("sqlite"):
            problems.append("DATABASE_URL points at SQLite")
        if (
            self.default_settlement_mode == "platform"
            and "SANDBOX" in self.bank_account_iban.upper()
        ):
            problems.append("BANK_ACCOUNT_IBAN is still the sandbox value")
        if ":khazana@" in self.database_url:
            problems.append("DATABASE_URL still uses the development password")
        if "@" not in self.redis_url:
            problems.append("REDIS_URL has no password")
        for name, url in (("API_BASE_URL", self.api_base_url), ("WEB_BASE_URL", self.web_base_url)):
            if not url.startswith("https://"):
                problems.append(f"{name} is not https")
        if self.demo_mode:
            problems.append("DEMO_MODE must be off in production")
        if self.trusted_proxy_count == 0:
            # Behind a proxy with this at zero, every request appears to come
            # from the proxy's own address, so the per address limit on login
            # codes would lock everyone out after twenty sign ins an hour.
            problems.append("TRUSTED_PROXY_COUNT is 0; set it to 1 behind the Caddy proxy")
        if problems:
            raise RuntimeError("Unsafe production configuration: " + "; ".join(problems))


@lru_cache
def get_settings() -> Settings:
    return Settings()
