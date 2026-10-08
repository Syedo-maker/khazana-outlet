"""Test fixtures.

Every test gets a fresh SQLite database, so no test can depend on another
one's leftovers. SQLite rather than PostgreSQL keeps the suite fast enough to
run on every save; the PostgreSQL specific parts, meaning the triggers and the
row level policies, are covered by the migration job in CI.
"""

from __future__ import annotations

import os
from collections.abc import Iterator

import pytest

os.environ.setdefault("SECRET_KEY", "test-secret-key-that-is-long-enough-32")
os.environ.setdefault("ENVIRONMENT", "test")
os.environ.setdefault("AI_OFFLINE", "true")
os.environ.setdefault("OTP_DEV_ECHO", "true")
# A cooldown of zero, so a test can request two codes in a row without
# sleeping. The cooldown itself is tested explicitly where it matters.
os.environ.setdefault("OTP_RESEND_COOLDOWN_SECONDS", "0")

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker

from khazana.config import get_settings
from khazana.db import build_engine, get_db
from khazana.main import create_app
from khazana.models import (
    Base,
    Brand,
    BrandMember,
    BrandPolicy,
    Category,
    User,
)
from khazana.models.enums import (
    BrandMemberRole,
    UserRole,
    VerificationStatus,
    Visibility,
)

get_settings.cache_clear()


@pytest.fixture
def engine(tmp_path):  # type: ignore[no-untyped-def]
    url = f"sqlite:///{tmp_path / 'test.db'}"
    eng = build_engine(url)
    Base.metadata.create_all(eng)
    yield eng
    eng.dispose()


@pytest.fixture
def db(engine) -> Iterator[Session]:  # type: ignore[no-untyped-def]
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    session = factory()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def client(engine, db) -> Iterator[TestClient]:  # type: ignore[no-untyped-def]
    app = create_app()

    def _override() -> Iterator[Session]:
        yield db

    app.dependency_overrides[get_db] = _override
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


# ------------------------------------------------------------------ helpers


@pytest.fixture
def category(db: Session) -> Category:
    row = Category(name="Womenswear stitched", slug="womenswear-stitched")
    db.add(row)
    db.commit()
    return row


def make_brand(db: Session, *, name: str, slug: str, owner_phone: str) -> tuple[Brand, User]:
    """Create a verified brand with an owner and a policy row."""
    owner = User(
        phone=owner_phone,
        full_name=f"{name} Owner",
        role=UserRole.BRAND,
    )
    db.add(owner)
    db.flush()

    brand = Brand(
        name=name,
        slug=slug,
        city="Lahore",
        status=VerificationStatus.VERIFIED,
    )
    db.add(brand)
    db.flush()

    db.add(
        BrandPolicy(
            brand_id=brand.id,
            commission_percent=15,
            default_visibility=Visibility.PRIVATE,
        )
    )
    db.add(BrandMember(brand_id=brand.id, user_id=owner.id, role_in_brand=BrandMemberRole.OWNER))
    db.commit()
    return brand, owner


@pytest.fixture
def two_brands(db: Session) -> tuple[tuple[Brand, User], tuple[Brand, User]]:
    """Two unrelated brands, for the tenant isolation tests."""
    first = make_brand(db, name="Brand One", slug="brand-one", owner_phone="03001111111")
    second = make_brand(db, name="Brand Two", slug="brand-two", owner_phone="03002222222")
    return first, second


@pytest.fixture
def admin_user(db: Session) -> User:
    user = User(phone="03009999999", full_name="Admin", role=UserRole.ADMIN)
    db.add(user)
    db.commit()
    return user
