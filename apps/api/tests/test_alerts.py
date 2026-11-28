"""Alerts: plain email to one address, through any SMTP server.

No paid monitoring service. Anything that needs a person is recorded as an
alert row; the scheduler sends undelivered rows by SMTP every few minutes.
One alert of a kind per cooldown, so a job failing every half hour is one
email, not forty eight. With no SMTP configured, alerts are logged only.
"""

from __future__ import annotations

import os
import time
from collections.abc import Iterator
from datetime import timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any, ClassVar

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from khazana.config import get_settings
from khazana.models import Alert
from khazana.models.base import utcnow
from khazana.services import alert_service


class FakeSmtp:
    sent: ClassVar[list[dict[str, Any]]] = []
    fail: ClassVar[bool] = False

    def __init__(self, host: str, port: int, timeout: float = 0) -> None:
        self.host, self.port = host, port
        self.started_tls = False
        self.logged_in: tuple[str, str] | None = None

    def __enter__(self) -> FakeSmtp:
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def starttls(self, context: object = None) -> None:
        self.started_tls = True

    def login(self, user: str, password: str) -> None:
        self.logged_in = (user, password)

    def send_message(self, message: Any) -> None:
        if FakeSmtp.fail:
            raise OSError("connection refused")
        FakeSmtp.sent.append(
            {
                "to": message["To"],
                "from": message["From"],
                "subject": message["Subject"],
                "body": message.get_content(),
                "tls": self.started_tls,
                "login": self.logged_in,
            }
        )


@pytest.fixture
def smtp(monkeypatch: pytest.MonkeyPatch) -> Iterator[type[FakeSmtp]]:
    FakeSmtp.sent = []
    FakeSmtp.fail = False
    monkeypatch.setattr(alert_service.smtplib, "SMTP", FakeSmtp)
    for name, value in {
        "ALERT_EMAIL_TO": "ops@example.com",
        "ALERT_EMAIL_FROM": "alerts@example.com",
        "SMTP_HOST": "smtp.example.com",
        "SMTP_PORT": "587",
        "SMTP_USERNAME": "alerts@example.com",
        "SMTP_PASSWORD": "app-password-not-real",
    }.items():
        monkeypatch.setenv(name, value)
    get_settings.cache_clear()
    yield FakeSmtp
    get_settings.cache_clear()


def test_an_alert_is_recorded_then_sent_by_email(db: Session, smtp: type[FakeSmtp]) -> None:
    alert = alert_service.raise_alert(db, "job-failed", "Job risk failed", "Traceback in the log.")
    db.commit()
    assert alert is not None and alert.delivered_at is None

    assert alert_service.deliver_pending(db) == 1
    db.commit()
    [mail] = smtp.sent
    assert mail["to"] == "ops@example.com"
    assert mail["subject"] == f"[Khazana {get_settings().environment}] Job risk failed"
    assert "Traceback in the log." in mail["body"]
    assert mail["tls"] is True
    assert mail["login"] == ("alerts@example.com", "app-password-not-real")
    db.refresh(alert)
    assert alert.delivered_at is not None
    assert alert_service.deliver_pending(db) == 0, "sent once"


def test_one_alert_of_a_kind_per_cooldown(db: Session, smtp: type[FakeSmtp]) -> None:
    assert alert_service.raise_alert(db, "job-failed", "first", "") is not None
    assert alert_service.raise_alert(db, "job-failed", "second", "") is None
    assert alert_service.raise_alert(db, "backup-stale", "other kind", "") is not None
    earlier = db.scalars(select(Alert).where(Alert.kind == "job-failed")).one()
    earlier.created_at = utcnow() - timedelta(minutes=get_settings().alert_cooldown_minutes + 1)
    db.commit()
    assert alert_service.raise_alert(db, "job-failed", "after the cooldown", "") is not None


def test_a_failed_send_is_retried_later(db: Session, smtp: type[FakeSmtp]) -> None:
    alert_service.raise_alert(db, "job-failed", "x", "")
    smtp.fail = True
    assert alert_service.deliver_pending(db) == 0
    row = db.scalars(select(Alert)).one()
    assert row.delivered_at is None and row.attempts == 1 and "refused" in (row.last_error or "")
    smtp.fail = False
    assert alert_service.deliver_pending(db) == 1


def test_without_smtp_alerts_are_only_logged(db: Session, caplog: pytest.LogCaptureFixture) -> None:
    assert not alert_service.configured()
    alert_service.raise_alert(db, "job-failed", "Job risk failed", "")
    with caplog.at_level("WARNING"):
        assert alert_service.deliver_pending(db) == 0
    assert "Job risk failed" in caplog.text


def test_a_failing_scheduled_job_raises_an_alert(
    db: Session, engine, monkeypatch: pytest.MonkeyPatch
) -> None:  # type: ignore[no-untyped-def]
    from sqlalchemy.orm import sessionmaker

    from khazana import scheduler

    monkeypatch.setattr(scheduler, "get_session_factory", lambda: sessionmaker(bind=engine))

    def broken(session: Session) -> object:
        raise RuntimeError("boom")

    assert scheduler.run_job(scheduler.Job("broken", broken, every_minutes=5)) is False
    alert = db.scalars(select(Alert).where(Alert.kind == "job-failed:broken")).one()
    assert "broken" in alert.subject


def test_reaching_the_ai_cap_raises_an_alert(db: Session, monkeypatch: pytest.MonkeyPatch) -> None:
    from khazana.ai.gateway import cost, limits
    from khazana.core.errors import SpendLimitReached
    from khazana.models.enums import AiFeature

    monkeypatch.setenv("AI_DAILY_SPEND_LIMIT_USD", "0.10")
    get_settings.cache_clear()
    try:
        cost.record_spend(db, feature=AiFeature.PRICING, brand_id=None, cost_usd=Decimal("0.10"))
        db.commit()
        with pytest.raises(SpendLimitReached):
            limits.assert_within_budget(db, AiFeature.PRICING)
    finally:
        get_settings.cache_clear()
    alert = db.scalars(select(Alert).where(Alert.kind == "ai-cap-reached")).one()
    assert "manual" in alert.body


def test_an_old_backup_raises_an_alert(
    db: Session, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("BACKUP_DIR", str(tmp_path))
    get_settings.cache_clear()
    try:
        assert alert_service.check_backups(db) == "no backups yet"
        dump = tmp_path / "khazana-20261101-0200.dump"
        dump.write_bytes(b"x")
        old = time.time() - 30 * 3600
        os.utime(dump, (old, old))
        assert alert_service.check_backups(db).startswith("stale")
        assert db.scalars(select(Alert).where(Alert.kind == "backup-stale")).first()
        dump.touch()
        assert alert_service.check_backups(db).startswith("fresh")
    finally:
        get_settings.cache_clear()


def test_an_unhandled_api_error_raises_an_alert(engine, db: Session, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    from fastapi.testclient import TestClient
    from sqlalchemy.orm import sessionmaker

    from khazana import main

    monkeypatch.setattr(alert_service, "_session_factory", lambda: sessionmaker(bind=engine))
    app = main.create_app()

    @app.get("/boom-for-test")
    def boom() -> None:
        raise RuntimeError("a bug")

    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.get("/boom-for-test")
    assert response.status_code == 500
    alert = db.scalars(select(Alert).where(Alert.kind == "server-error")).one()
    assert "/boom-for-test" in alert.body
    assert "a bug" not in alert.subject
