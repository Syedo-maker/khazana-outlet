"""Invite links: how people sign in when there is no SMS gateway.

SMS login codes cost money per message, so the pilot runs without them. An
admin creates a single use link for a person, sends it by hand (WhatsApp or
anything else), and the link signs that person in once. Every reseller who
joins this way is still verified by an admin before they can order.
"""

from __future__ import annotations

from datetime import timedelta
from urllib.parse import unquote

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from commerce_helpers import auth
from khazana.config import get_settings
from khazana.core.errors import Forbidden
from khazana.legal import TERMS_VERSION
from khazana.models import BrandMember, Invite, ResellerProfile, User
from khazana.models.base import as_utc, utcnow
from khazana.models.enums import UserRole, VerificationStatus
from khazana.services import invite_service, order_service

PHONE = "03215550101"


def _create(client: TestClient, admin: User, **body: object):  # type: ignore[no-untyped-def]
    payload = {"phone": PHONE, "full_name": "Bilal Cloth House", "role": "reseller", **body}
    return client.post("/admin/invites", json=payload, headers=auth(admin))


def _token(link: str) -> str:
    return link.rsplit("/join/", 1)[1]


def _accept(client: TestClient, token: str, **body: object):  # type: ignore[no-untyped-def]
    payload = {"accept_terms": True, "business_name": "Bilal Cloth House", "city": "Multan", **body}
    return client.post(f"/auth/invites/{token}/accept", json=payload)


class TestCreating:
    def test_an_admin_creates_a_link_to_send_by_hand(
        self, client: TestClient, db: Session, admin_user: User
    ) -> None:
        response = _create(client, admin_user)
        assert response.status_code == 201, response.text
        body = response.json()
        assert body["link"].startswith(get_settings().web_base_url + "/join/")
        assert body["purpose"] == "signup"
        token = _token(body["link"])
        assert len(token) >= 32
        stored = db.scalars(select(Invite)).one()
        assert stored.token_hash != token, "only a hash of the token is kept"
        assert token not in str(db.scalars(select(Invite.token_hash)).all())
        # A WhatsApp click to chat link, free and opened by the admin's own phone.
        assert body["whatsapp_url"].startswith("https://wa.me/923215550101?text=")
        assert body["link"] in unquote(body["whatsapp_url"])

    def test_only_admins_create_invites(self, client: TestClient, two_brands) -> None:  # type: ignore[no-untyped-def]
        (_, owner), _ = two_brands
        assert _create(client, owner).status_code == 403

    def test_nobody_is_invited_as_an_admin(self, client: TestClient, admin_user: User) -> None:
        assert _create(client, admin_user, role="admin").status_code == 422

    def test_an_existing_account_gets_a_sign_in_link(
        self, client: TestClient, db: Session, admin_user: User
    ) -> None:
        db.add(User(phone=PHONE, full_name="Existing", role=UserRole.RESELLER))
        db.commit()
        assert _create(client, admin_user).json()["purpose"] == "login"

    def test_the_list_never_shows_a_token(self, client: TestClient, admin_user: User) -> None:
        link = _create(client, admin_user).json()["link"]
        rows = client.get("/admin/invites", headers=auth(admin_user)).json()
        assert rows[0]["status"] == "pending"
        assert _token(link) not in str(rows)


class TestAccepting:
    def test_a_new_reseller_joins_and_waits_for_verification(
        self, client: TestClient, db: Session, admin_user: User
    ) -> None:
        token = _token(_create(client, admin_user).json()["link"])

        preview = client.get(f"/auth/invites/{token}").json()
        assert preview["valid"] is True
        assert preview["full_name"] == "Bilal Cloth House"
        assert preview["phone_hint"] == "0321*****01"
        assert preview["terms_version"] == TERMS_VERSION

        response = _accept(client, token)
        assert response.status_code == 200, response.text
        assert response.json()["access_token"]

        user = db.scalars(select(User).where(User.phone == PHONE)).one()
        assert user.role == UserRole.RESELLER
        assert user.terms_version == TERMS_VERSION
        assert user.terms_accepted_at is not None
        profile = db.scalars(
            select(ResellerProfile).where(ResellerProfile.user_id == user.id)
        ).one()
        assert VerificationStatus(profile.status) == VerificationStatus.PENDING
        with pytest.raises(Forbidden, match="verified"):
            order_service.require_buyer(db, user)

    def test_a_link_works_once(self, client: TestClient, admin_user: User) -> None:
        token = _token(_create(client, admin_user).json()["link"])
        assert _accept(client, token).status_code == 200
        again = _accept(client, token)
        assert again.status_code == 401
        assert "already been used" in again.text
        assert client.get(f"/auth/invites/{token}").json()["valid"] is False

    def test_an_expired_link_is_refused(
        self, client: TestClient, db: Session, admin_user: User
    ) -> None:
        token = _token(_create(client, admin_user).json()["link"])
        invite = db.scalars(select(Invite)).one()
        invite.expires_at = utcnow() - timedelta(minutes=1)
        db.commit()
        response = _accept(client, token)
        assert response.status_code == 401
        assert "expired" in response.text

    def test_a_revoked_link_is_refused(self, client: TestClient, admin_user: User) -> None:
        body = _create(client, admin_user).json()
        revoked = client.post(f"/admin/invites/{body['id']}/revoke", headers=auth(admin_user))
        assert revoked.status_code == 200
        assert revoked.json()["status"] == "revoked"
        assert _accept(client, _token(body["link"])).status_code == 401

    def test_a_made_up_token_is_refused_like_any_other(self, client: TestClient) -> None:
        assert _accept(client, "x" * 43).status_code == 401
        assert client.get(f"/auth/invites/{'x' * 43}").json()["valid"] is False

    def test_the_terms_must_be_accepted(self, client: TestClient, admin_user: User) -> None:
        token = _token(_create(client, admin_user).json()["link"])
        assert _accept(client, token, accept_terms=False).status_code == 422

    def test_a_sign_in_link_keeps_the_existing_account(
        self, client: TestClient, db: Session, two_brands, admin_user: User
    ) -> None:  # type: ignore[no-untyped-def]
        (_, owner), _ = two_brands
        body = _create(client, admin_user, phone=owner.phone, role="reseller").json()
        assert body["purpose"] == "login"
        assert _accept(client, _token(body["link"])).status_code == 200
        db.refresh(owner)
        assert owner.role == UserRole.BRAND, "a link never changes who someone is"

    def test_brand_staff_join_their_brand(
        self, client: TestClient, db: Session, two_brands, admin_user: User
    ) -> None:  # type: ignore[no-untyped-def]
        (brand, _), _ = two_brands
        token = _token(
            _create(
                client, admin_user, role="brand", brand_id=brand.id, full_name="Store manager"
            ).json()["link"]
        )
        assert _accept(client, token, business_name=None, city=None).status_code == 200
        user = db.scalars(select(User).where(User.phone == PHONE)).one()
        assert user.role == UserRole.BRAND
        assert db.scalars(
            select(BrandMember).where(
                BrandMember.user_id == user.id, BrandMember.brand_id == brand.id
            )
        ).first()


class TestWithoutSms:
    def test_asking_for_a_code_explains_the_invite_link(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("SMS_LOGIN_ENABLED", "false")
        monkeypatch.setenv("OTP_DEV_ECHO", "false")
        get_settings.cache_clear()
        try:
            response = client.post("/auth/otp/request", json={"phone": PHONE})
        finally:
            get_settings.cache_clear()
        assert response.status_code == 403
        assert "invite link" in response.text

    def test_development_still_shows_codes_on_screen(self, client: TestClient) -> None:
        # OTP_DEV_ECHO is on in development: no SMS is sent, so nothing costs.
        response = client.post("/auth/otp/request", json={"phone": PHONE})
        assert response.status_code == 200
        assert response.json()["dev_code"]

    def test_the_features_endpoint_says_what_is_switched_off(self, client: TestClient) -> None:
        features = client.get("/features").json()
        assert features["sms_login"] is False
        assert features["invite_only"] is True
        assert features["login_codes"] is True, "development shows codes on screen"
        assert features["whatsapp"] is False
        assert features["speech_to_text"] is False
        assert features["visual_search"] is False
        assert features["settlement_default"] == "direct"
        assert features["terms_version"] == TERMS_VERSION


class TestFirstAdmin:
    def test_the_server_prints_a_sign_in_link_for_the_first_admin(
        self, db: Session, capsys: pytest.CaptureFixture[str], engine
    ) -> None:  # type: ignore[no-untyped-def]
        from khazana import manage

        code = manage.main(
            ["create-admin", "--phone", "03335550000", "--name", "Pilot Admin"], engine=engine
        )
        assert code == 0
        link = capsys.readouterr().out.strip().splitlines()[-1]
        assert "/join/" in link
        admin = db.scalars(select(User).where(User.phone == "03335550000")).one()
        assert admin.role == UserRole.ADMIN

        assert manage.main(["login-link", "--phone", "03335550000"], engine=engine) == 0
        assert "/join/" in capsys.readouterr().out

    def test_invites_expire_after_the_configured_hours(self, db: Session, admin_user: User) -> None:
        invite, _ = invite_service.create(db, admin=admin_user, phone=PHONE, role=UserRole.RESELLER)
        hours = (as_utc(invite.expires_at) - as_utc(invite.created_at)).total_seconds() / 3600
        assert round(hours) == get_settings().invite_ttl_hours


def test_a_fresh_server_loads_the_category_list_once(
    db: Session, capsys: pytest.CaptureFixture[str], engine
) -> None:  # type: ignore[no-untyped-def]
    """Production starts empty and the demo seed is not for it: the category
    list, which listings must choose from, is loaded on its own."""
    from khazana import manage
    from khazana.models import Category
    from khazana.seed import CATEGORIES

    assert manage.main(["load-categories"], engine=engine) == 0
    expected = len(CATEGORIES) + sum(len(children) for _, _, children, _ in CATEGORIES)
    assert len(db.scalars(select(Category)).all()) == expected
    assert manage.main(["load-categories"], engine=engine) == 0, "running it again adds nothing"
    assert len(db.scalars(select(Category)).all()) == expected
    assert "already" in capsys.readouterr().out
