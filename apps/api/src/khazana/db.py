"""Engine, session factory and the request scoped session dependency."""

from __future__ import annotations

from collections.abc import Iterator

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from .config import get_settings


def build_engine(url: str | None = None) -> Engine:
    settings = get_settings()
    url = url or settings.database_url

    if url.startswith("sqlite"):
        # Tests only. StaticPool plus check_same_thread keeps one in memory or
        # one file database visible to the test client's thread.
        engine = create_engine(
            url,
            connect_args={"check_same_thread": False},
            echo=False,
            future=True,
        )

        @event.listens_for(engine, "connect")
        def _sqlite_pragmas(dbapi_connection, _record) -> None:  # type: ignore[no-untyped-def]
            # SQLite does not enforce foreign keys unless asked, and the whole
            # point of testing against it is to catch constraint violations.
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()

        return engine

    return create_engine(
        url,
        pool_pre_ping=True,
        pool_size=5,
        max_overflow=10,
        echo=False,
        future=True,
    )


_engine: Engine | None = None
_session_factory: sessionmaker[Session] | None = None


def get_engine() -> Engine:
    """The process wide engine, built on first use.

    Built lazily rather than at import time on purpose. Creating an engine
    eagerly imports the database driver, so a module level engine makes
    ``import khazana.db`` fail whenever the configured driver cannot load,
    even for code that never touches the database. That turns a configuration
    problem into an import error in unrelated tests, which is exactly how it
    was found.
    """
    # One engine per process, built once.
    global _engine
    if _engine is None:
        _engine = build_engine()
    return _engine


def get_session_factory() -> sessionmaker[Session]:
    global _session_factory
    if _session_factory is None:
        _session_factory = sessionmaker(bind=get_engine(), autoflush=False, expire_on_commit=False)
    return _session_factory


def reset_engine() -> None:
    """Drop the cached engine. Used by tests that change configuration."""
    global _engine, _session_factory
    if _engine is not None:
        _engine.dispose()
    _engine = None
    _session_factory = None


def get_db() -> Iterator[Session]:
    """FastAPI dependency. One session per request, always closed."""
    db = get_session_factory()()
    try:
        yield db
    finally:
        db.close()
