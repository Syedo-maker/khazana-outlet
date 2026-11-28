"""Operator alerts by plain email, through any SMTP server.

The pilot has no paid monitoring, so the platform watches itself and emails
one address (ALERT_EMAIL_TO) when something needs a person:

- a scheduled job failed,
- the AI daily budget ran out and features switched to their manual paths,
- the newest database backup is older than BACKUP_MAX_AGE_HOURS,
- the API stopped answering its readiness check,
- the uploads disk is nearly full,
- the API returned a server error.

``raise_alert`` only writes a row, so nothing a buyer does waits on SMTP. The
scheduler's ``deliver-alerts`` job sends undelivered rows every five minutes
and retries a failed send. One alert of a kind is kept per cooldown, so a job
failing every half hour is one email, not forty eight. With no SMTP settings
the alert is written to the log only. Alerts never carry personal data.

docs/deployment.md, "Alerts by email", says which free SMTP service to use.
"""

from __future__ import annotations

import logging
import shutil
import smtplib
import ssl
from collections.abc import Callable
from datetime import timedelta
from email.message import EmailMessage
from pathlib import Path

import httpx
from sqlalchemy import select
from sqlalchemy.engine import Connection, Engine
from sqlalchemy.orm import Session, sessionmaker

from ..config import get_settings
from ..models import Alert
from ..models.base import utcnow

logger = logging.getLogger("khazana.alerts")

MAX_ATTEMPTS = 5


def _session_factory() -> Callable[[], Session]:
    from ..db import get_session_factory

    return get_session_factory()


def configured() -> bool:
    settings = get_settings()
    return bool(settings.alert_email_to and settings.smtp_host)


def raise_alert(
    db: Session, kind: str, subject: str, body: str, *, cooldown_minutes: int | None = None
) -> Alert | None:
    """Record an alert, unless one of this kind was raised within the cooldown.

    Does not commit: the caller's transaction carries it.
    """
    minutes = cooldown_minutes or get_settings().alert_cooldown_minutes
    since = utcnow() - timedelta(minutes=minutes)
    recent = db.scalars(
        select(Alert.id).where(Alert.kind == kind[:80], Alert.created_at >= since).limit(1)
    ).first()
    if recent is not None:
        return None
    alert = Alert(kind=kind[:80], subject=subject[:200], body=body[:5000])
    db.add(alert)
    db.flush()
    logger.warning("alert %s: %s", kind, subject)
    return alert


def raise_alert_now(
    kind: str,
    subject: str,
    body: str,
    *,
    bind: Engine | Connection | None = None,
    cooldown_minutes: int | None = None,
) -> None:
    """Record an alert in its own transaction, whatever happens to the caller's.

    For a request that is about to fail or roll back. Never raises: an alert
    that cannot be written is logged, and the original problem goes on.
    """
    try:
        factory: Callable[[], Session] = (
            sessionmaker(bind=bind) if bind is not None else _session_factory()
        )
        with factory() as session:
            raise_alert(session, kind, subject, body, cooldown_minutes=cooldown_minutes)
            session.commit()
    except Exception:
        logger.exception("could not record alert %s: %s", kind, subject)


def deliver_pending(db: Session, *, limit: int = 20) -> int:
    """Email alerts not yet sent. Returns how many were sent."""
    rows = db.scalars(
        select(Alert).where(Alert.status == "pending").order_by(Alert.created_at).limit(limit)
    ).all()
    if not rows:
        return 0
    if not configured():
        for row in rows:
            logger.warning("alert not emailed, no SMTP configured: %s", row.subject)
            row.status = "logged"
            row.attempts += 1
        db.flush()
        return 0

    sent = 0
    for row in rows:
        row.attempts += 1
        try:
            _send(row)
        except Exception as exc:
            row.last_error = str(exc)[:500]
            if row.attempts >= MAX_ATTEMPTS:
                row.status = "failed"
            logger.warning("alert email failed (attempt %d): %s", row.attempts, exc)
            continue
        row.status = "sent"
        row.delivered_at = utcnow()
        sent += 1
    db.flush()
    return sent


def _send(alert: Alert) -> None:
    settings = get_settings()
    assert settings.smtp_host and settings.alert_email_to
    message = EmailMessage()
    message["Subject"] = f"[Khazana {settings.environment}] {alert.subject}"
    message["From"] = settings.alert_email_from or settings.smtp_username or settings.alert_email_to
    message["To"] = settings.alert_email_to
    message.set_content(
        f"{alert.body}\n\n"
        f"Kind: {alert.kind}\n"
        f"Raised: {alert.created_at:%Y-%m-%d %H:%M} UTC\n"
        f"Server: {settings.web_base_url}\n\n"
        "Only one alert of each kind is sent per "
        f"{settings.alert_cooldown_minutes} minutes."
    )
    context = ssl.create_default_context()
    if settings.smtp_starttls:
        with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=15) as server:
            server.starttls(context=context)
            if settings.smtp_username:
                server.login(settings.smtp_username, settings.smtp_password or "")
            server.send_message(message)
    else:
        with smtplib.SMTP_SSL(
            settings.smtp_host, settings.smtp_port, timeout=15, context=context
        ) as server:
            if settings.smtp_username:
                server.login(settings.smtp_username, settings.smtp_password or "")
            server.send_message(message)


# ------------------------------------------------------------------ checks


def check_backups(db: Session) -> str:
    settings = get_settings()
    folder = Path(settings.backup_dir)
    dumps = list(folder.glob("khazana-*.dump")) if folder.is_dir() else []
    if not dumps:
        return "no backups yet"
    newest = max(dump.stat().st_mtime for dump in dumps)
    age_hours = (utcnow().timestamp() - newest) / 3600
    if age_hours > settings.backup_max_age_hours:
        raise_alert(
            db,
            "backup-stale",
            "The database backup is out of date",
            f"The newest backup in {folder} is {age_hours:.0f} hours old. "
            "Check the backup container: docker compose logs backup.",
        )
        return f"stale, {age_hours:.0f} hours old"
    return f"fresh, {age_hours:.0f} hours old"


def check_api(db: Session) -> str:
    url = get_settings().health_check_url
    if not url:
        return "no health check url"
    try:
        response = httpx.get(url, timeout=10)
        healthy = response.status_code == 200
        detail = f"status {response.status_code}"
    except httpx.HTTPError as exc:
        healthy = False
        detail = type(exc).__name__
    if not healthy:
        raise_alert(
            db,
            "api-down",
            "The API is not answering its readiness check",
            f"{url} answered {detail}. Check docker compose ps and the api logs.",
            cooldown_minutes=60,
        )
        return f"unhealthy, {detail}"
    return "healthy"


def check_disk(db: Session) -> str:
    settings = get_settings()
    path = Path(settings.storage_local_path)
    target = path if path.exists() else Path(".")
    usage = shutil.disk_usage(target)
    free_percent = 100 * usage.free / usage.total
    if free_percent < settings.disk_free_alert_percent:
        raise_alert(
            db,
            "disk-low",
            "The server disk is nearly full",
            f"{free_percent:.0f} percent free on the disk holding {target}. "
            "Old backups and uploads may need moving off the server.",
        )
    return f"{free_percent:.0f} percent free"


def ai_cap_reached(bind: Engine | Connection | None) -> None:
    settings = get_settings()
    raise_alert_now(
        "ai-cap-reached",
        "The AI daily budget is used up",
        f"Today's AI spend reached the cap of USD {settings.ai_daily_spend_limit_usd:.2f}. "
        "Every AI feature now shows its manual path until midnight UTC; nothing has "
        "stopped working. Raise AI_DAILY_SPEND_LIMIT_USD only if this happens often.",
        bind=bind,
        cooldown_minutes=24 * 60,
    )
