"""Unbranded listings must not show the brand in their photographs."""

from __future__ import annotations

import io
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from PIL import Image, ImageDraw, ImageStat
from sqlalchemy.orm import Session

from catalog_helpers import build_submitted_lot, jpeg_bytes, review_photos
from khazana.ai import images
from khazana.ai.features import logo_detection
from khazana.ai.logo_regions import Box
from khazana.ai.schemas import LogoDetection, LogoRegion
from khazana.core.errors import Conflict, ValidationFailed
from khazana.core.security import create_access_token
from khazana.models import Brand, Lot, ResellerProfile, User
from khazana.models.enums import (
    LotStatus,
    PhotoKind,
    PhotoProtectionStatus,
    UserRole,
    VerificationStatus,
    Visibility,
)
from khazana.services import approval_service, catalog_service, photo_protection_service
from khazana.storage import get_backend, read_object


def auth(user: User) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(user.id, user.role)}"}


def patterned_jpeg() -> bytes:
    image = Image.new("RGB", (400, 400), (240, 240, 240))
    draw = ImageDraw.Draw(image)
    for index, x in enumerate(range(100, 300, 8)):
        fill = (0, 0, 0) if index % 2 == 0 else (255, 255, 255)
        draw.rectangle((x, 100, x + 7, 300), fill=fill)
    buffer = io.BytesIO()
    image.save(buffer, format="JPEG", quality=95)
    return buffer.getvalue()


def spread(data: bytes, box: tuple[int, int, int, int]) -> float:
    with Image.open(io.BytesIO(data)) as image:
        return ImageStat.Stat(image.convert("L").crop(box)).stddev[0]


@pytest.fixture
def owner_one(two_brands) -> tuple[Brand, User]:  # type: ignore[no-untyped-def]
    return two_brands[0]


@pytest.fixture
def owner_two(two_brands) -> tuple[Brand, User]:  # type: ignore[no-untyped-def]
    return two_brands[1]


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


@pytest.fixture
def unbranded_lot(db: Session, owner_one, category) -> Lot:  # type: ignore[no-untyped-def]
    brand, owner = owner_one
    brand.unbranded_label = "Leading lawn label"
    db.commit()
    lot = build_submitted_lot(db, brand, owner, category.id)
    approval_service.set_visibility(db, lot=lot, actor=owner, visibility=Visibility.UNBRANDED)
    db.commit()
    return lot


def publish(db: Session, lot: Lot, owner: User) -> None:
    approval_service.approve(db, lot=lot, actor=owner)
    db.commit()


class TestBlur:
    def test_the_region_loses_its_detail_and_the_rest_keeps_it(self) -> None:
        original = patterned_jpeg()
        hidden = images.blur_regions(original, [Box(0.25, 0.25, 0.25, 0.5)])

        assert spread(original, (100, 100, 200, 300)) > 80
        assert spread(hidden, (110, 110, 190, 290)) < 15
        assert spread(hidden, (210, 110, 290, 290)) > 80

    def test_a_box_at_the_edge_is_handled(self) -> None:
        assert images.blur_regions(patterned_jpeg(), [Box(0.9, 0.9, 0.5, 0.5)])


class TestDetectionRules:
    def _run(self, monkeypatch: pytest.MonkeyPatch, detection: LogoDetection, db: Session):  # type: ignore[no-untyped-def]
        monkeypatch.setattr(
            logo_detection,
            "run_feature",
            lambda *args, **kwargs: SimpleNamespace(output=detection),
        )
        return logo_detection.detect(
            db,
            image=b"x",
            photo_kind=PhotoKind.FRONT,
            brand_name="Brand",
            brand_id="brand",
        )

    def test_a_model_request_for_review_is_honoured(
        self, db: Session, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        detection = LogoDetection(
            regions=[],
            image_readable=True,
            needs_human_review=True,
            review_reason="A faint mark may be present",
        )
        outcome = self._run(monkeypatch, detection, db)
        assert outcome.needs_review
        assert "faint" in outcome.review_reasons[0]

    def test_an_oversized_blur_goes_to_a_person(
        self, db: Session, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        region = LogoRegion(kind="logo", x=0, y=0, width=0.9, height=0.9, confidence=0.9)
        detection = LogoDetection(
            regions=[region],
            image_readable=True,
            needs_human_review=False,
            review_reason=None,
        )
        assert self._run(monkeypatch, detection, db).needs_review


class TestScan:
    def test_only_unbranded_lots_are_scanned(self, db: Session, owner_one, category) -> None:  # type: ignore[no-untyped-def]
        brand, owner = owner_one
        lot = build_submitted_lot(db, brand, owner, category.id)
        with pytest.raises(Conflict, match="unbranded"):
            photo_protection_service.scan_lot(db, lot=lot, actor=owner)

    def test_found_marks_are_blurred_and_failures_stay_withheld(
        self, db: Session, unbranded_lot: Lot, owner_one
    ) -> None:  # type: ignore[no-untyped-def]
        """The front photo matches a committed reply, the other two have none."""
        brand, owner = owner_one
        brand.name = "QORVELLE"
        db.commit()

        photos = photo_protection_service.scan_lot(db, lot=unbranded_lot, actor=owner)
        db.commit()

        front = next(photo for photo in photos if photo.kind == PhotoKind.FRONT)
        assert front.protection_status == PhotoProtectionStatus.BLURRED
        assert front.blurred_file_key
        assert front.blurred_file_key != front.file_key
        assert get_backend().exists(front.blurred_file_key)

        # No reply for these two: the model could not answer, so they go to the
        # brand to mark by hand, and stay withheld from buyers meanwhile.
        others = [photo for photo in photos if photo.kind != PhotoKind.FRONT]
        assert {photo.protection_status for photo in others} == {PhotoProtectionStatus.NEEDS_REVIEW}
        assert {photo.protection_detail["source"] for photo in others} == {"manual"}
        assert photo_protection_service.buyer_photos(unbranded_lot) == []

    def test_with_ai_switched_off_every_photo_waits_for_the_brand(
        self, db: Session, unbranded_lot: Lot, owner_one, monkeypatch: pytest.MonkeyPatch
    ) -> None:  # type: ignore[no-untyped-def]
        from khazana.config import get_settings

        _, owner = owner_one
        monkeypatch.setenv("AI_ENABLED", "false")
        get_settings.cache_clear()
        try:
            photos = photo_protection_service.scan_lot(db, lot=unbranded_lot, actor=owner)
        finally:
            get_settings.cache_clear()
        assert {photo.protection_status for photo in photos} == {PhotoProtectionStatus.NEEDS_REVIEW}
        assert "switched off" in photos[0].protection_detail["message"]

    def test_a_reviewed_photo_is_not_paid_for_twice(
        self, db: Session, unbranded_lot: Lot, owner_one, monkeypatch: pytest.MonkeyPatch
    ) -> None:  # type: ignore[no-untyped-def]
        _, owner = owner_one
        review_photos(db, unbranded_lot, owner)

        def fail(*args: object, **kwargs: object) -> None:
            raise AssertionError("no model call was expected")

        monkeypatch.setattr(logo_detection, "detect", fail)
        photo_protection_service.scan_lot(db, lot=unbranded_lot, actor=owner)


class TestReview:
    def test_a_result_that_does_not_exist_cannot_be_accepted(
        self, db: Session, unbranded_lot: Lot, owner_one
    ) -> None:  # type: ignore[no-untyped-def]
        _, owner = owner_one
        with pytest.raises(ValidationFailed, match="no finished result"):
            photo_protection_service.review_photo(
                db,
                lot=unbranded_lot,
                photo_id=unbranded_lot.photos[0].id,
                actor=owner,
                regions=None,
            )

    def test_brand_chosen_areas_are_blurred(
        self, db: Session, unbranded_lot: Lot, owner_one
    ) -> None:  # type: ignore[no-untyped-def]
        _, owner = owner_one
        photo = photo_protection_service.review_photo(
            db,
            lot=unbranded_lot,
            photo_id=unbranded_lot.photos[0].id,
            actor=owner,
            regions=[Box(0.1, 0.1, 0.2, 0.2)],
        )
        assert photo.protection_status == PhotoProtectionStatus.BLURRED
        assert photo_protection_service.buyer_file_key(unbranded_lot, photo) == (
            photo.blurred_file_key
        )

    def test_a_replaced_protected_copy_is_deleted(
        self, db: Session, unbranded_lot: Lot, owner_one
    ) -> None:  # type: ignore[no-untyped-def]
        _, owner = owner_one
        photo = unbranded_lot.photos[0]
        region = [Box(0.1, 0.1, 0.2, 0.2)]
        photo_protection_service.review_photo(
            db, lot=unbranded_lot, photo_id=photo.id, actor=owner, regions=region
        )
        first_key = photo.blurred_file_key
        assert first_key
        photo_protection_service.review_photo(
            db, lot=unbranded_lot, photo_id=photo.id, actor=owner, regions=[]
        )
        assert photo.blurred_file_key is None
        assert not get_backend().exists(first_key)


class TestPublishingGate:
    def test_an_unreviewed_unbranded_lot_cannot_be_approved(
        self, db: Session, unbranded_lot: Lot, owner_one
    ) -> None:  # type: ignore[no-untyped-def]
        _, owner = owner_one
        with pytest.raises(Conflict, match="not been reviewed"):
            approval_service.approve(db, lot=unbranded_lot, actor=owner)

    def test_a_reviewed_lot_can_be_approved_and_records_the_buyer_photos(
        self, db: Session, unbranded_lot: Lot, owner_one
    ) -> None:  # type: ignore[no-untyped-def]
        _, owner = owner_one
        review_photos(db, unbranded_lot, owner)
        publish(db, unbranded_lot, owner)

        assert LotStatus(unbranded_lot.status) == LotStatus.LIVE
        snapshot = unbranded_lot.approvals[-1].snapshot
        assert len(snapshot["buyer_photo_keys"]) == 3

    def test_the_brand_name_in_the_listing_blocks_approval(
        self, db: Session, unbranded_lot: Lot, owner_one
    ) -> None:  # type: ignore[no-untyped-def]
        brand, owner = owner_one
        review_photos(db, unbranded_lot, owner)
        catalog_service.update_lot(
            db,
            lot=unbranded_lot,
            actor=owner,
            changes={"description": f"Original {brand.name} stock"},
        )
        db.commit()
        with pytest.raises(Conflict, match="brand name"):
            approval_service.approve(db, lot=unbranded_lot, actor=owner)

    def test_a_public_lot_needs_no_review(self, db: Session, owner_one, category) -> None:  # type: ignore[no-untyped-def]
        brand, owner = owner_one
        lot = build_submitted_lot(db, brand, owner, category.id)
        approval_service.approve(db, lot=lot, actor=owner, visibility=Visibility.PUBLIC)
        assert LotStatus(lot.status) == LotStatus.LIVE


class TestBuyerAccess:
    @pytest.fixture
    def live_lot(self, db: Session, unbranded_lot: Lot, owner_one) -> Lot:  # type: ignore[no-untyped-def]
        _, owner = owner_one
        photo_protection_service.review_photo(
            db,
            lot=unbranded_lot,
            photo_id=unbranded_lot.photos[0].id,
            actor=owner,
            regions=[Box(0.1, 0.1, 0.5, 0.5)],
        )
        for photo in unbranded_lot.photos[1:]:
            photo_protection_service.review_photo(
                db, lot=unbranded_lot, photo_id=photo.id, actor=owner, regions=[]
            )
        db.commit()
        publish(db, unbranded_lot, owner)
        return unbranded_lot

    def test_the_catalogue_carries_no_brand_identity(
        self, client: TestClient, live_lot: Lot, reseller: User, owner_one
    ) -> None:  # type: ignore[no-untyped-def]
        brand, _ = owner_one
        body = client.get("/catalog", headers=auth(reseller)).json()
        item = body["items"][0]
        assert item["brand_name"] == "Leading lawn label"
        assert "brand_id" not in item["lot"]
        assert brand.id not in str(body)
        assert brand.name not in str(body)

    def test_a_competing_brand_gets_the_label_too(
        self, client: TestClient, live_lot: Lot, owner_two
    ) -> None:  # type: ignore[no-untyped-def]
        _, competitor = owner_two
        body = client.get("/catalog", headers=auth(competitor)).json()
        assert body["items"][0]["brand_is_hidden"] is True

    def test_a_buyer_receives_the_protected_copy(
        self, client: TestClient, live_lot: Lot, reseller: User
    ) -> None:
        photo = live_lot.photos[0]
        response = client.get(f"/catalog/{live_lot.id}/photos/{photo.id}", headers=auth(reseller))
        assert response.status_code == 200
        assert response.headers["content-type"] == "image/jpeg"
        assert photo.blurred_file_key != photo.file_key
        assert response.content == read_object(photo.blurred_file_key or "")

    def test_an_unreviewed_photo_is_withheld_from_a_live_lot(
        self, client: TestClient, db: Session, live_lot: Lot, reseller: User
    ) -> None:
        photo = live_lot.photos[1]
        photo.protection_reviewed_at = None
        db.commit()

        detail = client.get(f"/catalog/{live_lot.id}", headers=auth(reseller)).json()
        assert photo.id not in {item["id"] for item in detail["photos"]}
        response = client.get(f"/catalog/{live_lot.id}/photos/{photo.id}", headers=auth(reseller))
        assert response.status_code == 404

    def test_the_owner_can_compare_both_versions(
        self, client: TestClient, live_lot: Lot, owner_one
    ) -> None:  # type: ignore[no-untyped-def]
        _, owner = owner_one
        photo = live_lot.photos[0]
        url = f"/lots/{live_lot.id}/photos/{photo.id}/image"
        assert client.get(url, headers=auth(owner)).content == read_object(photo.file_key)
        protected = client.get(f"{url}?variant=protected", headers=auth(owner))
        assert protected.content == read_object(photo.blurred_file_key or "")

    def test_another_brand_cannot_fetch_the_original(
        self, client: TestClient, live_lot: Lot, owner_two
    ) -> None:  # type: ignore[no-untyped-def]
        _, competitor = owner_two
        photo = live_lot.photos[0]
        response = client.get(
            f"/lots/{live_lot.id}/photos/{photo.id}/image", headers=auth(competitor)
        )
        assert response.status_code == 404

    def test_a_buyer_cannot_use_the_owner_path(
        self, client: TestClient, live_lot: Lot, reseller: User
    ) -> None:
        photo = live_lot.photos[0]
        response = client.get(
            f"/lots/{live_lot.id}/photos/{photo.id}/image", headers=auth(reseller)
        )
        assert response.status_code == 403


class TestPhotoRemoval:
    def test_the_protected_copy_goes_with_the_photo(self, db: Session, owner_one, category) -> None:  # type: ignore[no-untyped-def]
        brand, owner = owner_one
        lot = build_submitted_lot(db, brand, owner, category.id)
        extra = catalog_service.add_photo(
            db,
            lot=lot,
            actor=owner,
            data=jpeg_bytes(seed=50),
            content_type="image/jpeg",
            kind=PhotoKind.BACK,
        )
        photo_protection_service.review_photo(
            db, lot=lot, photo_id=extra.id, actor=owner, regions=[Box(0.1, 0.1, 0.1, 0.1)]
        )
        key = extra.blurred_file_key
        assert key
        catalog_service.remove_photo(db, lot=lot, actor=owner, photo_id=extra.id)
        assert not get_backend().exists(key)
