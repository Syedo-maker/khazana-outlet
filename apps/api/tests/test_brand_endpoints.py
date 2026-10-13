"""Brand portal endpoints.

Mostly authorisation. The service layer tests cover the behaviour; these cover
who is allowed to reach it, because that is where an HTTP layer goes wrong.
"""

from __future__ import annotations

import io

import pytest
from sqlalchemy.orm import Session

from khazana.models import User
from khazana.models.enums import UserRole
from khazana.services import auth_service


def png() -> bytes:
    from PIL import Image

    buffer = io.BytesIO()
    Image.new("RGB", (40, 40), (10, 20, 30)).save(buffer, format="PNG")
    return buffer.getvalue()


def token_for(db: Session, user: User) -> dict[str, str]:
    """Issue a real access token for an existing user."""
    _access, _refresh = auth_service.issue_session(db, user)
    access = auth_service.create_access_token(
        subject=user.id,
        role=user.role.value,
        brand_ids=auth_service.brand_ids_for(db, user),
    )
    db.commit()
    return {"Authorization": f"Bearer {access}"}


@pytest.fixture
def local_storage(tmp_path, monkeypatch):
    from khazana import storage
    from khazana.config import get_settings

    monkeypatch.setenv("STORAGE_LOCAL_PATH", str(tmp_path))
    get_settings.cache_clear()
    storage.reset_backend()
    yield tmp_path
    storage.reset_backend()
    get_settings.cache_clear()


@pytest.fixture
def buyer(db: Session) -> User:
    user = User(phone="03001234567", full_name="Buyer", role=UserRole.RESELLER)
    db.add(user)
    db.commit()
    return user


@pytest.fixture
def admin(db: Session) -> User:
    user = User(phone="03009999999", full_name="Admin", role=UserRole.ADMIN)
    db.add(user)
    db.commit()
    return user


class TestRegistration:
    def test_a_signed_in_user_can_register_a_brand(self, client, db: Session, buyer) -> None:
        response = client.post(
            "/brands",
            headers=token_for(db, buyer),
            json={"name": "Meher Textiles", "city": "Lahore"},
        )

        assert response.status_code == 201
        body = response.json()
        assert body["slug"] == "meher-textiles"
        assert body["status"] == "pending"

    def test_registration_requires_a_token(self, client) -> None:
        response = client.post("/brands", json={"name": "X Brand", "city": "Lahore"})
        assert response.status_code == 401

    def test_a_duplicate_name_answers_409(self, client, db: Session, buyer) -> None:
        headers = token_for(db, buyer)
        client.post("/brands", headers=headers, json={"name": "Meher", "city": "Lahore"})

        other = User(phone="03002222222", full_name="Other", role=UserRole.RESELLER)
        db.add(other)
        db.commit()

        response = client.post(
            "/brands", headers=token_for(db, other), json={"name": "meher", "city": "Karachi"}
        )
        assert response.status_code == 409


class TestTenantIsolation:
    def _two_brands(self, client, db: Session):
        first = User(phone="03001111111", full_name="One", role=UserRole.RESELLER)
        second = User(phone="03002222222", full_name="Two", role=UserRole.RESELLER)
        db.add_all([first, second])
        db.commit()

        a = client.post(
            "/brands", headers=token_for(db, first), json={"name": "Brand A", "city": "Lahore"}
        ).json()
        b = client.post(
            "/brands", headers=token_for(db, second), json={"name": "Brand B", "city": "Karachi"}
        ).json()
        return (first, a), (second, b)

    def test_a_brand_cannot_read_another_brands_dashboard(self, client, db: Session) -> None:
        """A cross tenant read answers 404, never 403.

        A 403 would confirm the other brand exists, which is itself a leak.
        """
        (first, _a), (_second, b) = self._two_brands(client, db)

        response = client.get(f"/brands/{b['id']}/dashboard", headers=token_for(db, first))
        assert response.status_code == 404

    def test_a_brand_cannot_change_another_brands_policy(self, client, db: Session) -> None:
        (first, _a), (_second, b) = self._two_brands(client, db)

        response = client.patch(
            f"/brands/{b['id']}/policy",
            headers=token_for(db, first),
            json={"commission_percent": 1},
        )
        assert response.status_code == 404

    def test_a_brand_reads_its_own_dashboard(self, client, db: Session) -> None:
        (first, a), _ = self._two_brands(client, db)

        response = client.get(f"/brands/{a['id']}/dashboard", headers=token_for(db, first))

        assert response.status_code == 200
        body = response.json()
        assert body["brand"]["id"] == a["id"]
        assert body["is_verified"] is False
        assert body["documents_missing"] == ["ntn", "incorporation"]


class TestPolicyEndpoint:
    def test_a_brand_updates_its_own_terms(self, client, db: Session, buyer) -> None:
        headers = token_for(db, buyer)
        brand = client.post(
            "/brands", headers=headers, json={"name": "Meher", "city": "Lahore"}
        ).json()
        headers = token_for(db, buyer)

        response = client.patch(
            f"/brands/{brand['id']}/policy",
            headers=headers,
            json={"commission_percent": 12, "allow_cod": True},
        )

        assert response.status_code == 200
        assert response.json()["commission_percent"] == 12
        assert response.json()["allow_cod"] is True

    def test_the_approval_gate_is_not_even_an_accepted_field(
        self, client, db: Session, buyer
    ) -> None:
        """Rejected by the schema, before it can reach the database constraint."""
        headers = token_for(db, buyer)
        brand = client.post(
            "/brands", headers=headers, json={"name": "Meher", "city": "Lahore"}
        ).json()

        response = client.patch(
            f"/brands/{brand['id']}/policy",
            headers=token_for(db, buyer),
            json={"require_brand_approval": False},
        )
        assert response.status_code == 422

    def test_an_empty_update_is_refused(self, client, db: Session, buyer) -> None:
        headers = token_for(db, buyer)
        brand = client.post(
            "/brands", headers=headers, json={"name": "Meher", "city": "Lahore"}
        ).json()

        response = client.patch(
            f"/brands/{brand['id']}/policy", headers=token_for(db, buyer), json={}
        )
        assert response.status_code == 400


class TestAdminOnlyRoutes:
    def _brand(self, client, db: Session, buyer):
        return client.post(
            "/brands", headers=token_for(db, buyer), json={"name": "Meher", "city": "Lahore"}
        ).json()

    def test_a_brand_cannot_reach_the_verification_queue(self, client, db: Session, buyer) -> None:
        self._brand(client, db, buyer)
        response = client.get("/brands/admin/verification-queue", headers=token_for(db, buyer))
        assert response.status_code == 403

    def test_a_brand_cannot_approve_itself(self, client, db: Session, buyer) -> None:
        brand = self._brand(client, db, buyer)

        response = client.post(
            f"/brands/{brand['id']}/review",
            headers=token_for(db, buyer),
            json={"approve": True},
        )
        assert response.status_code == 403

    def test_a_brand_cannot_suspend_anyone(self, client, db: Session, buyer, admin) -> None:
        brand = self._brand(client, db, buyer)

        response = client.post(
            f"/brands/{brand['id']}/suspend",
            headers=token_for(db, buyer),
            json={"reason": "I do not like them"},
        )
        assert response.status_code == 403

    def test_an_admin_sees_the_queue_and_can_decide(
        self, client, db: Session, buyer, admin, local_storage
    ) -> None:
        brand = self._brand(client, db, buyer)

        queue = client.get("/brands/admin/verification-queue", headers=token_for(db, admin))
        assert queue.status_code == 200
        assert brand["id"] in [row["id"] for row in queue.json()]

        # Rejection without a reason is refused.
        refused = client.post(
            f"/brands/{brand['id']}/review",
            headers=token_for(db, admin),
            json={"approve": False},
        )
        assert refused.status_code == 422

        accepted = client.post(
            f"/brands/{brand['id']}/review",
            headers=token_for(db, admin),
            json={"approve": False, "note": "The NTN certificate is unreadable."},
        )
        assert accepted.status_code == 200
        assert accepted.json()["status"] == "rejected"


class TestDocumentUpload:
    def test_a_document_uploads_and_appears_on_the_dashboard(
        self, client, db: Session, buyer, local_storage
    ) -> None:
        brand = client.post(
            "/brands", headers=token_for(db, buyer), json={"name": "Meher", "city": "Lahore"}
        ).json()

        response = client.post(
            f"/brands/{brand['id']}/documents",
            headers=token_for(db, buyer),
            data={"doc_type": "ntn"},
            files=[("file", ("ntn.png", png(), "image/png"))],
        )

        assert response.status_code == 201
        assert response.json()["doc_type"] == "ntn"
        assert response.json()["status"] == "pending"

        view = client.get(f"/brands/{brand['id']}/dashboard", headers=token_for(db, buyer))
        assert view.json()["documents_supplied"] == ["ntn"]
        assert view.json()["documents_missing"] == ["incorporation"]

    def test_a_file_pretending_to_be_an_image_is_refused(
        self, client, db: Session, buyer, local_storage
    ) -> None:
        brand = client.post(
            "/brands", headers=token_for(db, buyer), json={"name": "Meher", "city": "Lahore"}
        ).json()

        response = client.post(
            f"/brands/{brand['id']}/documents",
            headers=token_for(db, buyer),
            data={"doc_type": "ntn"},
            files=[("file", ("ntn.png", b"<html>nope</html>", "image/png"))],
        )
        assert response.status_code == 422

    def test_verification_cannot_be_requested_while_documents_are_missing(
        self, client, db: Session, buyer, local_storage
    ) -> None:
        brand = client.post(
            "/brands", headers=token_for(db, buyer), json={"name": "Meher", "city": "Lahore"}
        ).json()

        response = client.post(
            f"/brands/{brand['id']}/request-verification", headers=token_for(db, buyer)
        )
        assert response.status_code == 422
        assert "documents" in response.json()["detail"]["message"]


class TestOpenApiContract:
    def test_the_brand_operations_are_named_and_documented(self, client) -> None:
        spec = client.get("/openapi.json").json()

        ops = {
            op["operationId"]: op
            for path, methods in spec["paths"].items()
            if path.startswith("/brands")
            for method, op in methods.items()
            if method in {"get", "post", "patch", "put"}
        }

        for expected in (
            "brands_register",
            "brands_dashboard",
            "brands_upload_document",
            "brands_request_verification",
            "brands_update_policy",
            "brands_review",
            "brands_suspend",
        ):
            assert expected in ops, f"{expected} is missing"
            assert ops[expected].get("summary"), f"{expected} has no summary"
