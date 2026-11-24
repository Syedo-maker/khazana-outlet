"""A public demo: sample accounts only, offered on the login page, never in production."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from commerce_helpers import make_reseller
from khazana import scheduler
from khazana.config import get_settings


@pytest.fixture
def demo(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(get_settings(), "demo_mode", True)


def test_a_real_deployment_lists_no_accounts(client: TestClient, db: Session) -> None:
    make_reseller(db)
    assert client.get("/demo").json() == {"enabled": False, "accounts": []}


def test_a_demo_offers_one_sample_account_per_role(
    client: TestClient, db: Session, demo, two_brands, admin_user
) -> None:  # type: ignore[no-untyped-def]
    make_reseller(db)
    body = client.get("/demo").json()
    assert body["enabled"] is True
    assert [account["role"] for account in body["accounts"]] == ["reseller", "brand", "admin"]


def test_only_sample_accounts_can_sign_in_to_a_demo(client: TestClient, db: Session, demo) -> None:  # type: ignore[no-untyped-def]
    make_reseller(db, phone="03007777777")
    stranger = client.post("/auth/otp/request", json={"phone": "03001231234"})
    assert stranger.status_code == 403
    assert "sample accounts" in stranger.json()["detail"]["message"]
    assert client.post("/auth/otp/request", json={"phone": "03007777777"}).status_code == 200


def test_the_nightly_reset_does_nothing_outside_a_demo(db: Session) -> None:
    assert scheduler._demo_reset(db) == "skipped, not a demo"
