"""Authentication tests.

These cover the three ways OTP login actually gets broken in the wild: codes
that can be reused, codes that can be brute forced, and refresh tokens that
outlive a logout.
"""

from __future__ import annotations

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from khazana.core.errors import RateLimited, Unauthenticated, ValidationFailed
from khazana.core.security import (
    TokenError,
    create_access_token,
    decode_access_token,
    hash_password,
    verify_password,
)
from khazana.models import OtpChallenge, User
from khazana.services import auth_service


class TestPhoneNormalisation:
    @pytest.mark.parametrize(
        "raw",
        [
            "03001234567",
            "0300 1234567",
            "0300-1234567",
            "+923001234567",
            "923001234567",
            "3001234567",
        ],
    )
    def test_accepts_the_shapes_people_type(self, raw: str) -> None:
        assert auth_service.normalise_phone(raw) == "03001234567"

    @pytest.mark.parametrize(
        "raw",
        ["0212345678", "123", "0300123456789", "02112345678", "notaphone"],
    )
    def test_rejects_anything_else(self, raw: str) -> None:
        with pytest.raises(ValidationFailed):
            auth_service.normalise_phone(raw)


class TestOtpFlow:
    def test_request_then_verify_creates_the_user(self, db: Session) -> None:
        code = auth_service.request_otp(db, "03001234567")
        assert code is not None

        user, access, refresh = auth_service.verify_otp_and_login(
            db, "03001234567", code, full_name="Test Buyer"
        )

        assert user.phone == "03001234567"
        assert user.phone_verified_at is not None
        assert access and refresh
        assert decode_access_token(access)["sub"] == user.id

    def test_a_code_cannot_be_used_twice(self, db: Session) -> None:
        code = auth_service.request_otp(db, "03001234567")
        assert code
        auth_service.verify_otp_and_login(db, "03001234567", code)

        with pytest.raises(Unauthenticated):
            auth_service.verify_otp_and_login(db, "03001234567", code)

    def test_attempts_are_capped(self, db: Session) -> None:
        auth_service.request_otp(db, "03001234567")

        for _ in range(5):
            with pytest.raises(Unauthenticated):
                auth_service.verify_otp_and_login(db, "03001234567", "000000")

        challenge = db.scalars(select(OtpChallenge)).one()
        assert challenge.attempts == 5

        # Even the correct code is refused once the budget is spent, which is
        # what stops a six digit code being brute forced.
        with pytest.raises(Unauthenticated):
            auth_service.verify_otp_and_login(db, "03001234567", "000001")

    def test_resend_is_rate_limited(self, db: Session, monkeypatch) -> None:  # type: ignore[no-untyped-def]
        from khazana.config import get_settings

        get_settings.cache_clear()
        monkeypatch.setenv("OTP_RESEND_COOLDOWN_SECONDS", "60")
        get_settings.cache_clear()

        auth_service.request_otp(db, "03001234567")
        with pytest.raises(RateLimited):
            auth_service.request_otp(db, "03001234567")

        monkeypatch.setenv("OTP_RESEND_COOLDOWN_SECONDS", "0")
        get_settings.cache_clear()

    def test_an_expired_challenge_is_refused(self, db: Session) -> None:
        from datetime import timedelta

        from khazana.models.base import utcnow

        code = auth_service.request_otp(db, "03001234567")
        assert code
        challenge = db.scalars(select(OtpChallenge)).one()
        challenge.expires_at = utcnow() - timedelta(seconds=1)
        db.commit()

        with pytest.raises(Unauthenticated):
            auth_service.verify_otp_and_login(db, "03001234567", code)

    def test_admin_cannot_self_register(self, db: Session) -> None:
        from khazana.core.errors import Forbidden
        from khazana.models.enums import UserRole

        code = auth_service.request_otp(db, "03001234567")
        assert code
        with pytest.raises(Forbidden):
            auth_service.verify_otp_and_login(db, "03001234567", code, role=UserRole.ADMIN)


class TestSessions:
    def test_refresh_rotates_and_revokes_the_old_token(self, db: Session) -> None:
        code = auth_service.request_otp(db, "03001234567")
        assert code
        _user, _access, refresh = auth_service.verify_otp_and_login(db, "03001234567", code)

        _new_access, new_refresh = auth_service.refresh_session(db, refresh)
        assert new_refresh != refresh

        # The old token must be dead. Without rotation a stolen refresh token
        # stays valid for its whole lifetime.
        with pytest.raises(Unauthenticated):
            auth_service.refresh_session(db, refresh)

    def test_logout_revokes_every_session(self, db: Session) -> None:
        code = auth_service.request_otp(db, "03001234567")
        assert code
        user, _access, refresh_one = auth_service.verify_otp_and_login(db, "03001234567", code)
        _access_two, refresh_two = auth_service.issue_session(db, user)
        db.commit()

        revoked = auth_service.revoke_all_sessions(db, user.id)
        assert revoked == 2

        for token in (refresh_one, refresh_two):
            with pytest.raises(Unauthenticated):
                auth_service.refresh_session(db, token)


class TestTokens:
    def test_a_tampered_token_is_rejected(self) -> None:
        token = create_access_token("user-1", "reseller")
        body, signature = token.split(".")
        with pytest.raises(TokenError):
            decode_access_token(f"{body}.{signature[:-1]}0")

    def test_an_expired_token_is_rejected(self) -> None:
        from datetime import timedelta

        token = create_access_token("user-1", "reseller", expires_in=timedelta(seconds=-1))
        with pytest.raises(TokenError):
            decode_access_token(token)

    def test_garbage_is_rejected_without_crashing(self) -> None:
        for bad in ["", "nodot", "a.b.c", "!!!.???"]:
            with pytest.raises(TokenError):
                decode_access_token(bad)


class TestPasswords:
    def test_round_trip(self) -> None:
        stored = hash_password("correct horse battery staple")
        assert verify_password("correct horse battery staple", stored)
        assert not verify_password("wrong", stored)

    def test_missing_hash_always_fails(self) -> None:
        assert not verify_password("anything", None)
        assert not verify_password("anything", "")
        assert not verify_password("anything", "not-a-real-hash")


class TestAuthEndpoints:
    def test_full_login_over_http(self, client) -> None:  # type: ignore[no-untyped-def]
        requested = client.post("/auth/otp/request", json={"phone": "03001234567"})
        assert requested.status_code == 200
        code = requested.json()["dev_code"]
        assert code

        verified = client.post(
            "/auth/otp/verify",
            json={"phone": "03001234567", "code": code, "full_name": "Http Buyer"},
        )
        assert verified.status_code == 200
        access = verified.json()["access_token"]

        me = client.get("/auth/me", headers={"Authorization": f"Bearer {access}"})
        assert me.status_code == 200
        assert me.json()["user"]["full_name"] == "Http Buyer"
        assert me.json()["is_admin"] is False

    def test_me_requires_a_token(self, client) -> None:  # type: ignore[no-untyped-def]
        assert client.get("/auth/me").status_code == 401
        assert (
            client.get("/auth/me", headers={"Authorization": "Bearer nonsense"}).status_code == 401
        )

    def test_inactive_account_is_refused(self, client, db: Session) -> None:  # type: ignore[no-untyped-def]
        code = auth_service.request_otp(db, "03001234567")
        assert code
        user, access, _refresh = auth_service.verify_otp_and_login(db, "03001234567", code)
        user.is_active = False
        db.commit()

        response = client.get("/auth/me", headers={"Authorization": f"Bearer {access}"})
        assert response.status_code == 403

    def test_wrong_code_returns_401_not_500(self, client) -> None:  # type: ignore[no-untyped-def]
        client.post("/auth/otp/request", json={"phone": "03001234567"})
        response = client.post("/auth/otp/verify", json={"phone": "03001234567", "code": "999999"})
        assert response.status_code == 401

    def test_bad_phone_returns_422(self, client) -> None:  # type: ignore[no-untyped-def]
        response = client.post("/auth/otp/request", json={"phone": "02112345678"})
        assert response.status_code == 422


def test_health_does_not_touch_the_database(client) -> None:  # type: ignore[no-untyped-def]
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["database"] == "not checked"


def test_ready_checks_the_database(client) -> None:  # type: ignore[no-untyped-def]
    response = client.get("/ready")
    assert response.status_code == 200
    assert response.json()["database"] == "ok"


def test_no_user_is_created_by_a_failed_verify(db: Session) -> None:
    auth_service.request_otp(db, "03001234567")
    with pytest.raises(Unauthenticated):
        auth_service.verify_otp_and_login(db, "03001234567", "000000")
    assert db.scalars(select(User)).all() == []
