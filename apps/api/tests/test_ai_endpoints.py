"""The AI endpoints.

These test the HTTP layer, not the features behind it: authentication, tenant
ownership, upload validation, and that every AI response reports what it cost.
The behaviour of each capability is covered in its own test module.
"""

from __future__ import annotations

import io

import pytest
from sqlalchemy.orm import Session

from khazana.models import Category
from khazana.services import auth_service


def auth_header(db: Session, phone: str = "03001234567") -> dict[str, str]:
    code = auth_service.request_otp(db, phone)
    assert code
    _user, access, _refresh = auth_service.verify_otp_and_login(db, phone, code)
    return {"Authorization": f"Bearer {access}"}


def png_bytes(width: int = 400, height: int = 400) -> bytes:
    from PIL import Image

    image = Image.new("RGB", (width, height), (90, 120, 60))
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


@pytest.fixture
def category(db: Session) -> Category:
    row = Category(name="Womenswear stitched", slug="womenswear-stitched")
    db.add(row)
    db.commit()
    return row


class TestAuthentication:
    @pytest.mark.parametrize(
        ("method", "path"),
        [
            ("post", "/ai/listings/draft"),
            ("post", "/ai/manifests/extract"),
            ("post", "/ai/assistant/ask"),
            ("get", "/ai/search?q=lawn"),
        ],
    )
    def test_every_ai_endpoint_requires_a_token(self, client, method: str, path: str) -> None:
        response = getattr(client, method)(path)
        assert response.status_code == 401

    def test_the_status_endpoint_stays_open(self, client) -> None:
        """Operational visibility should not need a login.

        It exposes the mode, the routed models and the spend cap, none of
        which is sensitive, and it is more useful when it always answers.
        """
        response = client.get("/ai/status")
        assert response.status_code == 200
        assert response.json()["mode"] == "offline"


class TestOwnership:
    def test_a_brand_cannot_draft_a_listing_for_another_brand(
        self, client, db: Session, two_brands
    ) -> None:
        """A cross tenant write answers 404, not 403.

        A 403 would confirm the other brand exists, which is itself a leak.
        """
        (_first, owner), (second, _) = two_brands
        code = auth_service.request_otp(db, owner.phone)
        assert code
        _user, access, _refresh = auth_service.verify_otp_and_login(db, owner.phone, code)

        response = client.post(
            "/ai/listings/draft",
            headers={"Authorization": f"Bearer {access}"},
            data={"brand_id": second.id},
            files=[("files", ("a.png", png_bytes(), "image/png"))],
        )

        assert response.status_code == 404

    def test_a_reseller_cannot_use_the_brand_endpoints(self, client, db: Session) -> None:
        headers = auth_header(db)
        response = client.post(
            "/ai/manifests/extract",
            headers=headers,
            data={"brand_id": "whatever"},
            files=[("file", ("stock.csv", b"size,colour,pieces\n", "text/csv"))],
        )
        assert response.status_code == 403


class TestUploadValidation:
    def test_a_file_that_is_not_an_image_is_refused(
        self, client, db: Session, two_brands
    ) -> None:
        """The declared content type is not trusted.

        An HTML file uploaded as image/png and served back later is stored
        cross site scripting, so the magic bytes decide.
        """
        (brand, owner), _ = two_brands
        code = auth_service.request_otp(db, owner.phone)
        assert code
        _user, access, _refresh = auth_service.verify_otp_and_login(db, owner.phone, code)

        response = client.post(
            "/ai/listings/draft",
            headers={"Authorization": f"Bearer {access}"},
            data={"brand_id": brand.id},
            files=[("files", ("evil.png", b"<html>not an image</html>", "image/png"))],
        )

        assert response.status_code == 400
        assert "does not look like an image" in response.json()["detail"]["message"]

    def test_a_real_image_declared_as_the_wrong_type_is_refused(
        self, client, db: Session, two_brands
    ) -> None:
        """The other half of the check: valid bytes, lying content type.

        This is the branch that catches a file renamed to slip past a filter,
        and it reports the mismatch rather than a generic rejection.
        """
        (brand, owner), _ = two_brands
        code = auth_service.request_otp(db, owner.phone)
        assert code
        _user, access, _refresh = auth_service.verify_otp_and_login(db, owner.phone, code)

        response = client.post(
            "/ai/listings/draft",
            headers={"Authorization": f"Bearer {access}"},
            data={"brand_id": brand.id},
            files=[("files", ("a.jpg", png_bytes(50, 50), "image/jpeg"))],
        )

        assert response.status_code == 400
        assert "contents are" in response.json()["detail"]["message"]

    def test_too_many_photographs_is_refused_before_any_cost(
        self, client, db: Session, two_brands
    ) -> None:
        (brand, owner), _ = two_brands
        code = auth_service.request_otp(db, owner.phone)
        assert code
        _user, access, _refresh = auth_service.verify_otp_and_login(db, owner.phone, code)

        files = [("files", (f"{i}.png", png_bytes(50, 50), "image/png")) for i in range(9)]
        response = client.post(
            "/ai/listings/draft",
            headers={"Authorization": f"Bearer {access}"},
            data={"brand_id": brand.id},
            files=files,
        )

        assert response.status_code == 400
        assert "at most" in response.json()["detail"]["message"]


class TestSearch:
    def test_sqlite_explains_itself_rather_than_returning_nothing(
        self, client, db: Session
    ) -> None:
        """An empty list would be indistinguishable from a genuine miss."""
        headers = auth_header(db)
        response = client.get("/ai/search?q=lawn+suits", headers=headers)

        assert response.status_code == 400
        assert "PostgreSQL" in response.json()["detail"]["message"]


class TestOpenApiContract:
    def test_every_operation_has_an_explicit_id(self, client) -> None:
        """Auto generated ids produce unusable client method names."""
        spec = client.get("/openapi.json").json()

        auto = [
            op["operationId"]
            for path, ops in spec["paths"].items()
            for method, op in ops.items()
            if method in {"get", "post", "patch", "delete"}
            and f"_{method}" in op.get("operationId", "")
        ]
        assert not auto, f"these operations have auto generated ids: {auto}"

    def test_the_ai_operations_are_named_and_tagged_consistently(self, client) -> None:
        spec = client.get("/openapi.json").json()

        ai_ops = {
            op["operationId"]: op
            for path, ops in spec["paths"].items()
            for method, op in ops.items()
            if method in {"get", "post"} and path.startswith("/ai/")
        }

        assert "ai_listing_draft" in ai_ops
        assert "ai_manifest_extract" in ai_ops
        assert "ai_price_suggest" in ai_ops
        assert "ai_search_lots" in ai_ops
        assert "ai_assistant_ask" in ai_ops
        assert "ai_risk_score" in ai_ops

        for name, op in ai_ops.items():
            if name == "ops_ai_status":
                continue
            assert op.get("summary"), f"{name} has no summary"
            assert "ai" in op.get("tags", []), f"{name} is not tagged ai"

    def test_the_spend_cap_response_is_documented(self, client) -> None:
        """A 402 is unusual enough that a client author must be told about it."""
        spec = client.get("/openapi.json").json()
        draft = spec["paths"]["/ai/listings/draft"]["post"]
        assert "402" in draft["responses"]
        assert "spend cap" in draft["responses"]["402"]["description"]
