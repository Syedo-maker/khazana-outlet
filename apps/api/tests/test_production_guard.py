"""Production refuses to start with a configuration that would leak or break.

``assert_production_ready`` runs at startup. Every check here is a mistake
that has a concrete cost: a printed login code, a known password, a cookie
sent in clear, or a rate limit that locks every user out at once.
"""

from __future__ import annotations

import pytest

from khazana.config import Settings

SAFE = {
    "environment": "production",
    "secret_key": "x" * 48,
    "otp_dev_echo": False,
    "ai_offline": False,
    "anthropic_api_key": "sk-test-not-real",
    "database_url": "postgresql+psycopg://khazana:long-random-password@db:5432/khazana",
    "redis_url": "redis://:another-long-password@redis:6379/0",
    "api_base_url": "https://api.example.pk",
    "web_base_url": "https://example.pk",
    "bank_account_iban": "PK36SCBL0000001123456702",
    "trusted_proxy_count": 1,
}


def _settings(**overrides: object) -> Settings:
    return Settings(**{**SAFE, **overrides})  # type: ignore[arg-type]


def test_a_safe_configuration_starts() -> None:
    _settings().assert_production_ready()


def test_development_is_never_checked() -> None:
    Settings(environment="development").assert_production_ready()


@pytest.mark.parametrize(
    ("override", "message"),
    [
        ({"secret_key": "insecure-development-key-change-me"}, "SECRET_KEY"),
        ({"secret_key": "short"}, "shorter than 32"),
        ({"otp_dev_echo": True}, "OTP_DEV_ECHO"),
        ({"ai_offline": True}, "AI_OFFLINE"),
        ({"anthropic_api_key": None}, "ANTHROPIC_API_KEY"),
        ({"database_url": "sqlite:///x.db"}, "SQLite"),
        (
            {"database_url": "postgresql+psycopg://khazana:khazana@db:5432/khazana"},
            "development password",
        ),
        ({"redis_url": "redis://redis:6379/0"}, "REDIS_URL has no password"),
        ({"api_base_url": "http://api.example.pk"}, "API_BASE_URL is not https"),
        ({"web_base_url": "http://example.pk"}, "WEB_BASE_URL is not https"),
        (
            {
                "bank_account_iban": "PK00SANDBOX0000000000000",
                "default_settlement_mode": "platform",
            },
            "sandbox",
        ),
        ({"trusted_proxy_count": 0}, "TRUSTED_PROXY_COUNT"),
        ({"demo_mode": True}, "DEMO_MODE"),
    ],
)
def test_each_unsafe_setting_stops_startup(override: dict[str, object], message: str) -> None:
    with pytest.raises(RuntimeError, match=message):
        _settings(**override).assert_production_ready()


def test_the_zero_budget_pilot_starts_with_ai_off_and_no_bank_account() -> None:
    """Direct settlement holds no money, so the platform needs no account, and
    with AI switched off there is no key to require."""
    _settings(
        ai_enabled=False,
        anthropic_api_key=None,
        ai_offline=True,
        default_settlement_mode="direct",
        bank_account_iban="PK00SANDBOX0000000000000",
    ).assert_production_ready()


def test_ai_switched_on_still_needs_a_key() -> None:
    with pytest.raises(RuntimeError, match="AI_ENABLED=false"):
        _settings(ai_enabled=True, anthropic_api_key=None).assert_production_ready()
