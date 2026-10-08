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


engine = build_engine()
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def get_db() -> Iterator[Session]:
    """FastAPI dependency. One session per request, always closed."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
