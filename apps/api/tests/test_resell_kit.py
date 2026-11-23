"""The resell kit: who may have one, what the model is told, and what code adds.

The model is replaced by a stub that records its inputs. The test that matters
most checks those inputs: for an unbranded lot the brand never reaches the
model, and the retail price never does for any lot.
"""

from __future__ import annotations

import io
import json
from dataclasses import dataclass
from typing import Any

import pytest
from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy.orm import Session

from catalog_helpers import build_submitted_lot, review_photos
from commerce_helpers import auth, live_lot, make_courier, make_reseller, whole_order
from khazana.ai.schemas import ResellKitCopy
from khazana.models import Lot, Order, ResellKit, User
from khazana.models.enums import OrderStatus, Visibility
from khazana.services import approval_service, resell_kit_service

COPY = ResellKitCopy(
    caption_en="New printed lawn suits at Multan Cloth House.",
    caption_ur_roman="Multan Cloth House par naye lawn suits.",
    caption_ur="ملتان کلاتھ ہاؤس پر نئے لان سوٹ۔",  # noqa: RUF001
    social_post="Printed lawn suits, Rs 650 per piece. WhatsApp us.",
    whatsapp_status="Lawn suits, Rs 650.",
    hashtags=["#lawn"],
    selling_points=["New and unused"],
)


@dataclass
class _Result:
    output: ResellKitCopy


@pytest.fixture
def model(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    calls: list[dict[str, Any]] = []

    def fake_run_feature(db: Session, feature: Any, **kwargs: Any) -> _Result:
        calls.append(kwargs)
        return _Result(output=COPY)

    monkeypatch.setattr(resell_kit_service, "run_feature", fake_run_feature)
    return calls


def _paid_order(db: Session, two_brands, category, visibility: Visibility) -> Order:  # type: ignore[no-untyped-def]
    (brand, owner), _ = two_brands
    make_courier(db)
    if visibility == Visibility.UNBRANDED:
        # An unbranded lot needs every photograph reviewed before approval.
        lot = build_submitted_lot(db, brand, owner, category.id)
        review_photos(db, lot, owner)
        approval_service.approve(db, lot=lot, actor=owner, visibility=visibility)
        db.commit()
    else:
        lot = live_lot(db, brand, owner, category.id, visibility=visibility)
    order = whole_order(db, make_reseller(db), lot)
    order.status = OrderStatus.PAID
    db.commit()
    return order


class TestWhatTheModelIsTold:
    def test_an_unbranded_lot_never_sends_the_brand(
        self,
        db: Session,
        two_brands,
        category,
        model,  # type: ignore[no-untyped-def]
    ) -> None:
        order = _paid_order(db, two_brands, category, Visibility.UNBRANDED)
        buyer = db.get(User, order.buyer_user_id)
        resell_kit_service.generate(db, user=buyer, order_id=order.id, selling_price_pkr=650)

        sent = json.dumps(model[0]["prompt_values"], ensure_ascii=False)
        assert "Brand One" not in sent
        assert resell_kit_service.HIDDEN_BRAND in sent

    def test_the_retail_price_is_never_sent(
        self,
        db: Session,
        two_brands,
        category,
        model,  # type: ignore[no-untyped-def]
    ) -> None:
        order = _paid_order(db, two_brands, category, Visibility.PUBLIC)
        buyer = db.get(User, order.buyer_user_id)
        resell_kit_service.generate(db, user=buyer, order_id=order.id, selling_price_pkr=650)

        values = model[0]["prompt_values"]
        facts = json.loads(values["facts"])
        assert facts["brand"] == "Brand One"
        assert "1000" not in values["facts"] and "1,000" not in values["facts"]
        assert "retail" not in values["facts"].lower()
        assert values["selling_price_pkr"] == 650
        assert values["shop_name"] == "Multan Cloth House"


class TestKit:
    def test_tags_and_catalogue_come_from_the_order_lines(
        self,
        db: Session,
        two_brands,
        category,
        model,  # type: ignore[no-untyped-def]
    ) -> None:
        order = _paid_order(db, two_brands, category, Visibility.PUBLIC)
        buyer = db.get(User, order.buyer_user_id)
        kit = resell_kit_service.generate(db, user=buyer, order_id=order.id, selling_price_pkr=1250)
        assert len(kit.price_tags) == len(order.lines)
        assert {tag["price_en"] for tag in kit.price_tags} == {"Rs 1,250"}
        assert {tag["price_ur"] for tag in kit.price_tags} == {"1,250 روپے"}
        assert "*Multan Cloth House*" in kit.whatsapp_catalogue
        for line in order.lines:
            assert f"- {line.size}, {line.color}: Rs 1,250" in kit.whatsapp_catalogue

    def test_regenerating_replaces_the_kit(
        self,
        db: Session,
        two_brands,
        category,
        model,  # type: ignore[no-untyped-def]
    ) -> None:
        order = _paid_order(db, two_brands, category, Visibility.PUBLIC)
        buyer = db.get(User, order.buyer_user_id)
        resell_kit_service.generate(db, user=buyer, order_id=order.id, selling_price_pkr=600)
        resell_kit_service.generate(db, user=buyer, order_id=order.id, selling_price_pkr=700)
        rows = db.query(ResellKit).all()
        assert len(rows) == 1 and rows[0].selling_price_pkr == 700

    def test_an_unpaid_order_has_no_kit(
        self,
        db: Session,
        two_brands,
        category,
        model,  # type: ignore[no-untyped-def]
    ) -> None:
        order = _paid_order(db, two_brands, category, Visibility.PUBLIC)
        order.status = OrderStatus.CANCELLED
        db.commit()
        buyer = db.get(User, order.buyer_user_id)
        with pytest.raises(resell_kit_service.Conflict):
            resell_kit_service.generate(db, user=buyer, order_id=order.id, selling_price_pkr=600)
        assert model == []


class TestEndpoints:
    def test_no_kit_yet_is_an_empty_answer_not_an_error(
        self,
        client: TestClient,
        db: Session,
        two_brands,
        category,
        model,  # type: ignore[no-untyped-def]
    ) -> None:
        order = _paid_order(db, two_brands, category, Visibility.PUBLIC)
        buyer = db.get(User, order.buyer_user_id)
        response = client.get(f"/orders/{order.id}/resell-kit", headers=auth(buyer))
        assert response.status_code == 200
        assert response.json() is None

    def test_another_buyer_gets_a_404(
        self,
        client: TestClient,
        db: Session,
        two_brands,
        category,
        model,  # type: ignore[no-untyped-def]
    ) -> None:
        order = _paid_order(db, two_brands, category, Visibility.PUBLIC)
        stranger = make_reseller(db, phone="03008888888")
        response = client.post(
            f"/orders/{order.id}/resell-kit",
            json={"selling_price_pkr": 650},
            headers=auth(stranger),
        )
        assert response.status_code == 404
        assert model == []

    def test_generate_view_and_square_photo(
        self,
        client: TestClient,
        db: Session,
        two_brands,
        category,
        model,  # type: ignore[no-untyped-def]
    ) -> None:
        order = _paid_order(db, two_brands, category, Visibility.PUBLIC)
        buyer = db.get(User, order.buyer_user_id)
        assert db.get(Lot, order.lot_id).photos, "the helper lot has photographs"

        made = client.post(
            f"/orders/{order.id}/resell-kit",
            json={"selling_price_pkr": 650},
            headers=auth(buyer),
        )
        assert made.status_code == 200, made.text
        body = made.json()
        assert body["caption_ur"] == COPY.caption_ur
        assert client.get(f"/orders/{order.id}/resell-kit", headers=auth(buyer)).status_code == 200

        photo = client.get(body["photo_paths"][0], headers=auth(buyer))
        assert photo.status_code == 200
        with Image.open(io.BytesIO(photo.content)) as image:
            assert image.width == image.height
