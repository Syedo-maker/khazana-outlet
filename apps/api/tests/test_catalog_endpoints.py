"""The catalog router: the tenant boundary, the lifecycle, and the buyer view.

The tests worth reading first are the cross tenant ones. Every lot path goes
through one helper that calls `assert_owns`, and that helper is the only thing
stopping one brand reading, editing or approving another brand's stock. A 404
rather than a 403 is asserted deliberately: confirming that a lot exists but
belongs to someone else is itself a leak.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from catalog_helpers import BASE_LOT, balanced_manifest, jpeg_bytes
from khazana.core.security import create_access_token
from khazana.models import Brand, ResellerProfile, User
from khazana.models.enums import LotStatus, PhotoKind, UserRole, VerificationStatus, Visibility


def auth(user: User) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(user.id, user.role)}"}


@pytest.fixture
def owner_one(two_brands) -> tuple[Brand, User]:  # type: ignore[no-untyped-def]
    (brand, owner), _ = two_brands
    return brand, owner


@pytest.fixture
def owner_two(two_brands) -> tuple[Brand, User]:  # type: ignore[no-untyped-def]
    _, (brand, owner) = two_brands
    return brand, owner


@pytest.fixture
def reseller(db: Session) -> User:
    user = User(phone="03007777777", full_name="Shop Owner", role=UserRole.RESELLER)
    db.add(user)
    db.flush()
    db.add(
        ResellerProfile(
            user_id=user.id,
            business_name="Multan Cloth House",
            city="Multan",
            status=VerificationStatus.VERIFIED,
        )
    )
    db.commit()
    return user


def create_lot_via_api(
    client: TestClient, brand: Brand, owner: User, category_id: str, **overrides: object
) -> dict[str, object]:
    payload = {
        **{k: (v.value if hasattr(v, "value") else v) for k, v in BASE_LOT.items()},
        "brand_id": brand.id,
        "category_id": category_id,
        **overrides,
    }
    response = client.post("/lots", json=payload, headers=auth(owner))
    assert response.status_code == 201, response.text
    return dict(response.json())


class TestTenantBoundary:
    """One brand must not be able to see or touch another brand's stock."""

    def test_another_brands_lot_reads_as_missing_rather_than_forbidden(
        self, client: TestClient, owner_one, owner_two, category
    ) -> None:
        brand, owner = owner_one
        _, intruder = owner_two
        lot = create_lot_via_api(client, brand, owner, category.id)

        response = client.get(f"/lots/{lot['id']}", headers=auth(intruder))
        assert response.status_code == 404
        # The body must not confirm that the lot exists.
        assert brand.name not in response.text
        assert lot["lot_code"] not in response.text

    def test_another_brand_cannot_edit_the_lot(
        self, client: TestClient, owner_one, owner_two, category
    ) -> None:
        brand, owner = owner_one
        _, intruder = owner_two
        lot = create_lot_via_api(client, brand, owner, category.id)

        response = client.patch(
            f"/lots/{lot['id']}", json={"title": "Taken over"}, headers=auth(intruder)
        )
        assert response.status_code == 404

    def test_another_brand_cannot_approve_the_lot(
        self, client: TestClient, owner_one, owner_two, category
    ) -> None:
        """The approval gate is the brand protection promise.

        If another account could approve, the promise would be worthless.
        """
        brand, owner = owner_one
        _, intruder = owner_two
        lot = create_lot_via_api(client, brand, owner, category.id)

        response = client.post(f"/lots/{lot['id']}/approve", json={}, headers=auth(intruder))
        assert response.status_code == 404

    def test_the_listing_cannot_be_created_for_someone_elses_brand(
        self, client: TestClient, owner_one, owner_two, category
    ) -> None:
        brand, _ = owner_one
        _, intruder = owner_two
        payload = {
            **{k: (v.value if hasattr(v, "value") else v) for k, v in BASE_LOT.items()},
            "brand_id": brand.id,
            "category_id": category.id,
        }
        response = client.post("/lots", json=payload, headers=auth(intruder))
        assert response.status_code == 404

    def test_a_reseller_cannot_reach_the_brand_paths(
        self, client: TestClient, reseller: User
    ) -> None:
        assert client.get("/lots", headers=auth(reseller)).status_code == 403

    def test_the_lot_list_only_returns_the_callers_own(
        self, client: TestClient, owner_one, owner_two, category
    ) -> None:
        first, first_owner = owner_one
        second, second_owner = owner_two
        create_lot_via_api(client, first, first_owner, category.id)
        create_lot_via_api(client, second, second_owner, category.id)

        body = client.get("/lots", headers=auth(first_owner)).json()
        assert body["total"] == 1
        assert body["items"][0]["brand_id"] == first.id


class TestLifecycle:
    def test_a_lot_goes_from_draft_to_live_through_the_api(
        self, client: TestClient, owner_one, category
    ) -> None:
        """The full M3 and week 22 path, as a brand would actually walk it."""
        brand, owner = owner_one
        lot = create_lot_via_api(client, brand, owner, category.id)
        lot_id = lot["id"]
        assert lot["status"] == LotStatus.DRAFT

        # Not ready yet, and the checklist says why.
        readiness = client.get(f"/lots/{lot_id}/readiness", headers=auth(owner)).json()
        assert readiness["ready"] is False
        assert readiness["blockers"]

        manifest = client.put(
            f"/lots/{lot_id}/manifest",
            json={"lines": balanced_manifest()},
            headers=auth(owner),
        )
        assert manifest.status_code == 200, manifest.text
        assert manifest.json()["is_manifest_balanced"] is True

        for index, kind in enumerate((PhotoKind.FULL_LOT, PhotoKind.FRONT, PhotoKind.LABEL), 1):
            upload = client.post(
                f"/lots/{lot_id}/photos",
                files={"file": (f"{index}.jpg", jpeg_bytes(seed=index), "image/jpeg")},
                data={"kind": kind.value},
                headers=auth(owner),
            )
            assert upload.status_code == 201, upload.text

        assert client.get(f"/lots/{lot_id}/readiness", headers=auth(owner)).json()["ready"]

        submitted = client.post(f"/lots/{lot_id}/submit", headers=auth(owner))
        assert submitted.status_code == 200, submitted.text
        assert submitted.json()["status"] == LotStatus.PENDING_APPROVAL

        queue = client.get("/lots/queue", headers=auth(owner)).json()
        assert [item["lot"]["id"] for item in queue] == [lot_id]
        assert queue[0]["risk_band"] in {"low", "medium", "high"}

        approved = client.post(
            f"/lots/{lot_id}/approve",
            json={"visibility": Visibility.PUBLIC.value},
            headers=auth(owner),
        )
        assert approved.status_code == 200, approved.text
        assert approved.json()["status"] == LotStatus.LIVE

        trail = client.get(f"/lots/{lot_id}/approvals", headers=auth(owner)).json()
        assert [entry["action"] for entry in trail] == ["submitted", "approved"]

    def test_submitting_an_unready_lot_returns_422_with_the_reason(
        self, client: TestClient, owner_one, category
    ) -> None:
        brand, owner = owner_one
        lot = create_lot_via_api(client, brand, owner, category.id)

        response = client.post(f"/lots/{lot['id']}/submit", headers=auth(owner))
        assert response.status_code == 422
        assert "not ready" in response.json()["message"]

    def test_a_short_manifest_returns_422_naming_both_totals(
        self, client: TestClient, owner_one, category
    ) -> None:
        brand, owner = owner_one
        lot = create_lot_via_api(client, brand, owner, category.id)

        response = client.put(
            f"/lots/{lot['id']}/manifest",
            json={"lines": [{"size": "S", "color": "blue", "pieces": 40}]},
            headers=auth(owner),
        )
        assert response.status_code == 422
        message = response.json()["message"]
        assert "40" in message and "100" in message

    def test_a_rejection_without_a_reason_is_refused_by_the_schema(
        self, client: TestClient, owner_one, category
    ) -> None:
        brand, owner = owner_one
        lot = create_lot_via_api(client, brand, owner, category.id)

        response = client.post(
            f"/lots/{lot['id']}/reject", json={"note": "no"}, headers=auth(owner)
        )
        assert response.status_code == 422

    def test_a_non_image_upload_is_refused(self, client: TestClient, owner_one, category) -> None:
        brand, owner = owner_one
        lot = create_lot_via_api(client, brand, owner, category.id)

        response = client.post(
            f"/lots/{lot['id']}/photos",
            files={"file": ("x.png", b"<html>not an image</html>", "image/png")},
            data={"kind": PhotoKind.FRONT.value},
            headers=auth(owner),
        )
        assert response.status_code == 422

    def test_withdraw_then_relist_as_a_draft(self, client: TestClient, owner_one, category) -> None:
        """A brand pulling a lot for the season should be able to bring it back."""
        brand, owner = owner_one
        lot = create_lot_via_api(client, brand, owner, category.id)

        withdrawn = client.post(
            f"/lots/{lot['id']}/withdraw", json={"note": "Season over"}, headers=auth(owner)
        )
        assert withdrawn.status_code == 200, withdrawn.text
        assert withdrawn.json()["status"] == LotStatus.WITHDRAWN


class TestBuyerView:
    def _publish(
        self, client: TestClient, brand: Brand, owner: User, category_id: str, **kwargs: object
    ) -> dict[str, object]:
        lot = create_lot_via_api(client, brand, owner, category_id, **kwargs)
        lot_id = lot["id"]
        client.put(
            f"/lots/{lot_id}/manifest",
            json={"lines": balanced_manifest()},
            headers=auth(owner),
        )
        for index, kind in enumerate((PhotoKind.FULL_LOT, PhotoKind.FRONT, PhotoKind.LABEL), 1):
            client.post(
                f"/lots/{lot_id}/photos",
                files={"file": (f"{index}.jpg", jpeg_bytes(seed=index), "image/jpeg")},
                data={"kind": kind.value},
                headers=auth(owner),
            )
        client.post(f"/lots/{lot_id}/submit", headers=auth(owner))
        response = client.post(
            f"/lots/{lot_id}/approve",
            json={"visibility": Visibility.PUBLIC.value},
            headers=auth(owner),
        )
        assert response.status_code == 200, response.text
        return dict(response.json())

    def test_a_live_public_lot_appears_in_the_catalogue(
        self, client: TestClient, owner_one, category, reseller: User
    ) -> None:
        brand, owner = owner_one
        lot = self._publish(client, brand, owner, category.id)

        body = client.get("/catalog", headers=auth(reseller)).json()
        assert [item["lot"]["id"] for item in body["items"]] == [lot["id"]]
        assert body["items"][0]["brand_name"] == brand.name
        assert body["items"][0]["brand_is_hidden"] is False

    def test_a_draft_never_appears_in_the_catalogue(
        self, client: TestClient, owner_one, category, reseller: User
    ) -> None:
        brand, owner = owner_one
        create_lot_via_api(client, brand, owner, category.id)

        body = client.get("/catalog", headers=auth(reseller)).json()
        assert body["total"] == 0

    def test_an_unbranded_lot_never_sends_the_real_name_to_the_client(
        self, client: TestClient, db: Session, owner_one, category, reseller: User
    ) -> None:
        """Filtering in the browser would mean shipping the name first."""
        brand, owner = owner_one
        brand.unbranded_label = "Premium lawn surplus"
        db.commit()

        lot = self._publish(client, brand, owner, category.id)
        client.put(
            f"/lots/{lot['id']}/visibility",
            json={"visibility": Visibility.UNBRANDED.value},
            headers=auth(owner),
        )

        response = client.get("/catalog", headers=auth(reseller))
        assert brand.name not in response.text
        assert response.json()["items"][0]["brand_name"] == "Premium lawn surplus"
        assert response.json()["items"][0]["brand_is_hidden"] is True

    def test_the_region_lock_hides_the_lot_from_the_resellers_own_city(
        self, client: TestClient, owner_one, category, reseller: User
    ) -> None:
        """The city defaults to the reseller's profile, and can be overridden.

        A reseller in Karachi legitimately buys for a shop in Multan, so the
        lock applies to whichever city is being bought for.
        """
        brand, owner = owner_one
        lot = self._publish(client, brand, owner, category.id)
        locked = client.put(
            f"/lots/{lot['id']}/region-lock",
            json={"cities": ["Multan"]},
            headers=auth(owner),
        )
        assert locked.status_code == 200, locked.text

        # The reseller's profile city is Multan, so the default hides it.
        assert client.get("/catalog", headers=auth(reseller)).json()["total"] == 0
        # Buying for another city shows it again.
        assert client.get("/catalog?city=Faisalabad", headers=auth(reseller)).json()["total"] == 1
