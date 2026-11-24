"""The production scheduler: every job that runs on a timetable, in one process.

    python -m khazana.scheduler            run forever
    python -m khazana.scheduler --once     run every job once and exit

It runs from the API image as its own container (``scheduler`` in
docker-compose.prod.yml), and calls the services directly, not the admin HTTP
endpoints, so it needs no admin token and no network path to the API.

Times are Pakistan time, UTC+5 all year. Each job runs in its own database
session, and a failing job is logged and retried at its next slot without
stopping the others.
"""

from __future__ import annotations

import argparse
import logging
import signal
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta, timezone

from sqlalchemy.orm import Session

from .config import get_settings
from .db import get_session_factory
from .observability import configure_logging

logger = logging.getLogger("khazana.scheduler")

PKT = timezone(timedelta(hours=5), "PKT")


@dataclass(frozen=True, slots=True)
class Job:
    name: str
    run: Callable[[Session], object]
    # Either every N minutes, or once a day at HH:MM Pakistan time, optionally
    # only on one weekday (Monday is 0).
    every_minutes: int | None = None
    daily_at: tuple[int, int] | None = None
    weekday: int | None = None

    def next_after(self, moment: datetime) -> datetime:
        """The first time strictly after ``moment`` this job is due."""
        if self.every_minutes is not None:
            step = timedelta(minutes=self.every_minutes)
            epoch = datetime(2026, 1, 1, tzinfo=UTC)
            slots = (moment - epoch) // step + 1
            return epoch + slots * step
        assert self.daily_at is not None
        local = moment.astimezone(PKT)
        hour, minute = self.daily_at
        candidate = local.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if candidate <= local:
            candidate += timedelta(days=1)
        while self.weekday is not None and candidate.weekday() != self.weekday:
            candidate += timedelta(days=1)
        return candidate.astimezone(UTC)


def _markdown_submit(db: Session) -> object:
    from .services import markdown_service

    return len(markdown_service.submit_batch(db))


def _markdown_collect(db: Session) -> object:
    from .services import markdown_service

    return len(markdown_service.collect_batch(db))


def _expire_pools(db: Session) -> object:
    from .services import pool_service

    return pool_service.expire_pools(db)


def _close_dispute_windows(db: Session) -> object:
    from .services import order_service

    return order_service.close_expired_windows(db)


def _risk(db: Session) -> object:
    from .services import risk_service

    return risk_service.run(db)


def _forecast(db: Session) -> object:
    from .services import forecast_service

    return forecast_service.run(db)


def _demo_reset(db: Session) -> object:
    """Reseed a public demo every night, so a visitor's changes do not last."""
    if not get_settings().demo_mode:
        return "skipped, not a demo"
    from . import seed

    return seed.main(["--reset"])


def _purge_ai_cache(db: Session) -> object:
    from .ai.gateway import response_cache

    return response_cache.purge_expired(db)


JOBS: tuple[Job, ...] = (
    # Quiet hours first: the batch has the night to come back before buyers wake.
    Job("markdown-submit", _markdown_submit, daily_at=(2, 0)),
    Job("markdown-collect", _markdown_collect, every_minutes=30),
    Job("expire-pools", _expire_pools, every_minutes=60),
    Job("close-dispute-windows", _close_dispute_windows, every_minutes=60),
    Job("risk", _risk, daily_at=(3, 0)),
    Job("forecast", _forecast, daily_at=(4, 0), weekday=0),
    Job("purge-ai-cache", _purge_ai_cache, daily_at=(4, 30)),
    Job("demo-reset", _demo_reset, daily_at=(5, 0)),
)


def run_job(job: Job) -> bool:
    """Run one job in its own session. Returns whether it succeeded."""
    started = time.perf_counter()
    with get_session_factory()() as db:
        try:
            outcome = job.run(db)
            db.commit()
        except Exception:
            db.rollback()
            logger.exception("job %s failed", job.name)
            return False
    logger.info("job %s done in %.1fs: %s", job.name, time.perf_counter() - started, outcome)
    return True


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run Khazana's scheduled jobs")
    parser.add_argument("--once", action="store_true", help="run every job once and exit")
    args = parser.parse_args(argv)
    settings = get_settings()
    configure_logging(settings.log_format, settings.log_level)

    if args.once:
        return 0 if all(run_job(job) for job in JOBS) else 1

    stopping = False

    def _stop(*_: object) -> None:
        nonlocal stopping
        stopping = True

    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)

    now = datetime.now(UTC)
    due = {job.name: job.next_after(now) for job in JOBS}
    for job in JOBS:
        logger.info("scheduled %s, next at %s", job.name, due[job.name].astimezone(PKT))
    while not stopping:
        now = datetime.now(UTC)
        for job in JOBS:
            if due[job.name] <= now:
                run_job(job)
                due[job.name] = job.next_after(datetime.now(UTC))
        time.sleep(5)
    logger.info("scheduler stopped")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
