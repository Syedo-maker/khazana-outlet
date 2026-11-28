"""The scheduler's timetable, in Pakistan time, and how it handles a failing job."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from khazana import scheduler
from khazana.scheduler import JOBS, PKT, Job


def _job(name: str) -> Job:
    return next(job for job in JOBS if job.name == name)


def test_a_daily_job_runs_at_its_pakistan_time() -> None:
    # 01:00 PKT on a Tuesday is 20:00 UTC the evening before.
    moment = datetime(2026, 11, 24, 1, 0, tzinfo=PKT)
    due = _job("markdown-submit").next_after(moment)
    assert due.astimezone(PKT) == datetime(2026, 11, 24, 2, 0, tzinfo=PKT)
    later = _job("markdown-submit").next_after(due)
    assert later.astimezone(PKT) == datetime(2026, 11, 25, 2, 0, tzinfo=PKT)


def test_the_weekly_forecast_waits_for_monday() -> None:
    tuesday = datetime(2026, 11, 24, 12, 0, tzinfo=PKT)
    due = _job("forecast").next_after(tuesday).astimezone(PKT)
    assert due.weekday() == 0
    assert (due.hour, due.minute) == (4, 0)
    assert due.date().isoformat() == "2026-11-30"


def test_an_interval_job_lands_on_its_grid() -> None:
    moment = datetime(2026, 11, 24, 10, 7, 30, tzinfo=UTC)
    due = _job("markdown-collect").next_after(moment)
    assert due == datetime(2026, 11, 24, 10, 30, tzinfo=UTC)
    assert _job("markdown-collect").next_after(due) == datetime(2026, 11, 24, 11, 0, tzinfo=UTC)


def test_every_job_has_exactly_one_kind_of_schedule() -> None:
    for job in JOBS:
        assert (job.every_minutes is None) != (job.daily_at is None), job.name


def test_a_failing_job_is_reported_and_does_not_stop_the_others(
    db, monkeypatch: pytest.MonkeyPatch, caplog
) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(scheduler, "get_session_factory", lambda: lambda: db)

    def explode(_: object) -> object:
        raise RuntimeError("courier API down")

    assert scheduler.run_job(Job("broken", explode, every_minutes=60)) is False
    assert "job broken failed" in caplog.text
    assert scheduler.run_job(Job("fine", lambda _: 3, every_minutes=60)) is True


def test_running_every_job_once_works_on_an_empty_database(db, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(scheduler, "get_session_factory", lambda: lambda: db)
    for job in JOBS:
        assert scheduler.run_job(job), job.name


def test_the_loop_leaves_a_heartbeat_for_the_health_check(tmp_path) -> None:  # type: ignore[no-untyped-def]
    from khazana.scheduler import beat

    heartbeat = tmp_path / "beat"
    beat(heartbeat)
    assert heartbeat.exists()
