"""The size translator: brand sizes mapped to the standard by measurement."""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from commerce_helpers import auth, live_lot, make_reseller
from khazana.core.errors import ValidationFailed
from khazana.models import AuditLog, StandardSize
from khazana.services import size_service

WOMEN = [
    ("S", 82, 87, 66, 71),
    ("M", 87, 92, 71, 76),
    ("L", 92, 98, 76, 82),
    ("XL", 98, 105, 82, 89),
]


@pytest.fixture
def standard(db: Session) -> None:
    for label, c1, c2, w1, w2 in WOMEN:
        db.add(
            StandardSize(
                audience="women",
                label=label,
                chest_min_cm=c1,
                chest_max_cm=c2,
                waist_min_cm=w1,
                waist_max_cm=w2,
            )
        )
    db.commit()


def _row(label: str, chest: tuple[int, int], waist: tuple[int, int]) -> dict[str, Any]:
    return {
        "audience": "women",
        "label": label,
        "chest_min_cm": chest[0],
        "chest_max_cm": chest[1],
        "waist_min_cm": waist[0],
        "waist_max_cm": waist[1],
    }


def test_labels_are_normalised() -> None:
    assert size_service.normalise_label("Medium") == "M"
    assert size_service.normalise_label(" med ") == "M"
    assert size_service.normalise_label("Extra-Large") == "XL"
    assert size_service.normalise_label("32") == "32"


class TestGuide:
    def test_a_small_cut_brand_maps_its_m_to_the_standard_s(
        self,
        db: Session,
        two_brands,
        category,
        standard,  # type: ignore[no-untyped-def]
    ) -> None:
        (brand, owner), _ = two_brands
        size_service.replace_chart(
            db,
            brand_id=brand.id,
            actor=owner,
            rows=[
                _row("S", (78, 82), (62, 66)),
                _row("M", (82, 87), (66, 71)),
                _row("L", (87, 93), (71, 77)),
                _row("XL", (93, 99), (77, 83)),
            ],
        )
        lot = live_lot(db, brand, owner, category.id)
        guide = {g.size: g for g in size_service.guide_for(db, lot)}
        assert guide["M"].standard == "S" and guide["M"].match == "close"
        assert guide["L"].standard == "M"
        assert "chest 82 to 87 cm" in guide["M"].measurements

    def test_without_a_chart_nothing_is_guessed(
        self,
        db: Session,
        two_brands,
        category,
        standard,  # type: ignore[no-untyped-def]
    ) -> None:
        (brand, owner), _ = two_brands
        lot = live_lot(db, brand, owner, category.id)
        assert all(
            g.standard is None and g.match == "no chart" for g in size_service.guide_for(db, lot)
        )


class TestChart:
    def test_backwards_ranges_and_duplicates_are_refused(
        self,
        db: Session,
        two_brands,  # type: ignore[no-untyped-def]
    ) -> None:
        (brand, owner), _ = two_brands
        with pytest.raises(ValidationFailed, match="backwards"):
            size_service.replace_chart(
                db, brand_id=brand.id, actor=owner, rows=[_row("M", (92, 87), (71, 76))]
            )
        with pytest.raises(ValidationFailed, match="twice"):
            size_service.replace_chart(
                db,
                brand_id=brand.id,
                actor=owner,
                rows=[_row("M", (87, 92), (71, 76)), _row("Medium", (87, 92), (71, 76))],
            )

    def test_the_chart_endpoints_are_brand_scoped_and_audited(
        self,
        client: TestClient,
        db: Session,
        two_brands,
        standard,  # type: ignore[no-untyped-def]
    ) -> None:
        (brand, owner), (_, other_owner) = two_brands
        body = [_row("M", (87, 92), (71, 76))]
        saved = client.put(f"/brands/{brand.id}/size-chart", json=body, headers=auth(owner))
        assert saved.status_code == 200, saved.text
        assert saved.json()[0]["standard"] == "M"
        refused = client.put(f"/brands/{brand.id}/size-chart", json=body, headers=auth(other_owner))
        assert refused.status_code == 404
        assert db.scalar(select(AuditLog).where(AuditLog.action == "size_chart.replaced"))

    def test_buyers_see_the_guide_on_the_listing(
        self,
        client: TestClient,
        db: Session,
        two_brands,
        category,
        standard,  # type: ignore[no-untyped-def]
    ) -> None:
        (brand, owner), _ = two_brands
        size_service.replace_chart(
            db, brand_id=brand.id, actor=owner, rows=[_row("M", (87, 92), (71, 76))]
        )
        lot = live_lot(db, brand, owner, category.id)
        buyer = make_reseller(db)
        detail = client.get(f"/catalog/{lot.id}", headers=auth(buyer)).json()
        guide = {g["size"]: g for g in detail["size_guide"]}
        assert guide["M"]["standard"] == "M"
        assert guide["S"]["match"] == "no chart"
