"""Sessions end when they should, and code requests cannot be farmed.

Week 51's security pass found three gaps:

- Signing out revoked the refresh tokens but left every access token working
  until it expired, up to an hour later.
- A refresh token that had already been rotated was simply refused, so a
  thief who used a stolen one first kept the session and the real user was
  the one signed out.
- One network address could request login codes for any number of phone
  numbers, each an SMS somebody pays for, and the per address limit that
  should stop that would have trusted a client written X-Forwarded-For.
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session
from starlette.requests import Request

from khazana.api.deps import client_ip
from khazana.config import get_settings
from khazana.models import Session as UserSession
from khazana.models import User
from khazana.models.base import utcnow
from khazana.services import auth_service


def _sign_in(client: TestClient, phone: str = "03001112222") -> dict[str, str]:
    sent = client.post("/auth/otp/request", json={"phone": phone})
    assert sent.status_code == 200, sent.text
    pair = client.post("/auth/otp/verify", json={"phone": phone, "code": sent.json()["dev_code"]})
    assert pair.status_code == 200, pair.text
    return pair.json()


def _me(client: TestClient, access: str) -> int:
    return client.get("/auth/me", headers={"Authorization": f"Bearer {access}"}).status_code


class TestSigningOut:
    def test_logout_ends_the_access_token_at_once(self, client: TestClient) -> None:
        pair = _sign_in(client)
        assert _me(client, pair["access_token"]) == 200
        out = client.post(
            "/auth/logout", headers={"Authorization": f"Bearer {pair['access_token']}"}
        )
        assert out.status_code == 204
        assert _me(client, pair["access_token"]) == 401
        refreshed = client.post("/auth/refresh", json={"refresh_token": pair["refresh_token"]})
        assert refreshed.status_code == 401

    def test_signing_in_again_after_logout_works(self, client: TestClient, db: Session) -> None:
        first = _sign_in(client)
        client.post("/auth/logout", headers={"Authorization": f"Bearer {first['access_token']}"})
        # A sign in in the same second as the logout must not be refused.
        user = db.scalars(select(User).where(User.phone == "03001112222")).one()
        user.tokens_valid_after = utcnow() - timedelta(seconds=2)
        db.commit()
        again = _sign_in(client)
        assert _me(client, again["access_token"]) == 200

    def test_a_token_without_an_issue_time_is_refused_once_signed_out(self) -> None:
        user = User(phone="03001112222", full_name="x", tokens_valid_after=utcnow())
        assert auth_service.token_still_valid(user, {}) is False
        assert auth_service.token_still_valid(User(phone="0", full_name="y"), {}) is True


class TestRefreshRotation:
    def test_refresh_rotates_and_the_old_token_stops_working(self, client: TestClient) -> None:
        pair = _sign_in(client)
        new = client.post("/auth/refresh", json={"refresh_token": pair["refresh_token"]})
        assert new.status_code == 200, new.text
        assert new.json()["refresh_token"] != pair["refresh_token"]
        assert _me(client, new.json()["access_token"]) == 200
        again = client.post("/auth/refresh", json={"refresh_token": pair["refresh_token"]})
        assert again.status_code == 401

    def test_reuse_after_the_grace_period_signs_out_everywhere(
        self, client: TestClient, db: Session
    ) -> None:
        stolen = _sign_in(client)
        # The thief refreshes first and gets a working pair.
        thief = client.post("/auth/refresh", json={"refresh_token": stolen["refresh_token"]})
        assert thief.status_code == 200
        # A minute later the real user's copy of the old token turns up.
        for session in db.scalars(select(UserSession)).all():
            if session.revoked_at is not None:
                session.revoked_at = utcnow() - timedelta(minutes=5)
        db.commit()
        real = client.post("/auth/refresh", json={"refresh_token": stolen["refresh_token"]})
        assert real.status_code == 401
        # The thief is out too: their access token and their refresh token.
        assert _me(client, thief.json()["access_token"]) == 401
        assert (
            client.post(
                "/auth/refresh", json={"refresh_token": thief.json()["refresh_token"]}
            ).status_code
            == 401
        )

    def test_reuse_inside_the_grace_period_only_fails_that_request(
        self, client: TestClient
    ) -> None:
        pair = _sign_in(client)
        first = client.post("/auth/refresh", json={"refresh_token": pair["refresh_token"]})
        second = client.post("/auth/refresh", json={"refresh_token": pair["refresh_token"]})
        assert first.status_code == 200
        assert second.status_code == 401
        assert _me(client, first.json()["access_token"]) == 200, "two tabs, not a theft"


class TestCodeRequestsPerAddress:
    def test_one_address_cannot_request_codes_for_many_numbers(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(get_settings(), "otp_ip_hourly_limit", 3)
        for number in range(3):
            sent = client.post("/auth/otp/request", json={"phone": f"0300100000{number}"})
            assert sent.status_code == 200, sent.text
        refused = client.post("/auth/otp/request", json={"phone": "03001000009"})
        assert refused.status_code == 429
        assert "network" in refused.json()["detail"]["message"]

    def test_a_forged_forwarded_header_does_not_reset_the_count(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(get_settings(), "otp_ip_hourly_limit", 2)
        for number in range(2):
            client.post(
                "/auth/otp/request",
                json={"phone": f"0300200000{number}"},
                headers={"X-Forwarded-For": f"10.0.0.{number}"},
            )
        refused = client.post(
            "/auth/otp/request",
            json={"phone": "03002000009"},
            headers={"X-Forwarded-For": "10.9.9.9"},
        )
        assert refused.status_code == 429


def _request(forwarded: str | None, peer: str = "172.18.0.5") -> Request:
    headers = [(b"x-forwarded-for", forwarded.encode())] if forwarded else []
    return Request({"type": "http", "headers": headers, "client": (peer, 1234)})


class TestClientAddress:
    def test_the_header_is_ignored_with_no_trusted_proxy(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(get_settings(), "trusted_proxy_count", 0)
        assert client_ip(_request("1.2.3.4")) == "172.18.0.5"

    def test_behind_one_proxy_the_last_hop_is_the_client(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(get_settings(), "trusted_proxy_count", 1)
        # The client wrote 6.6.6.6 itself; the proxy appended the real 1.2.3.4.
        assert client_ip(_request("6.6.6.6, 1.2.3.4")) == "1.2.3.4"
        assert client_ip(_request(None)) == "172.18.0.5"
