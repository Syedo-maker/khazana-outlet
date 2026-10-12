"""Pricing suggestions.

The thing under test is honesty as much as arithmetic. A confident price with
no evidence behind it is the failure that costs a brand money and then costs
you the brand, so these tests check that the suggestion stays inside the
brand's band and admits when it is guessing.
"""

from __future__ import annotations

import json

import pytest
from sqlalchemy.orm import Session

from khazana.ai.features import pricing as feature
from khazana.ai.gateway import client, prompts
from khazana.ai.schemas import PriceSuggestion
from khazana.core.errors import NotFound
from khazana.models import Category, Lot, ManifestLine, Order
from khazana.models.enums import ConditionGrade, LotStatus, OrderStatus, Visibility


@pytest.fixture
def category(db: Session) -> Category:
    row = Category(name="Womenswear stitched", slug="womenswear-stitched")
    db.add(row)
    db.commit()
    return row


def make_lot(
    db: Session,
    brand_id: str,
    category_id: str,
    *,
    code: str = "LOT-P1",
    pieces: int = 100,
    sizes: dict[str, int] | None = None,
    status: LotStatus = LotStatus.DRAFT,
) -> Lot:
    sizes = sizes or {"M": pieces}
    total = sum(sizes.values())
    lot = Lot(
        lot_code=code,
        brand_id=brand_id,
        category_id=category_id,
        title="Lawn suits",
        condition_grade=ConditionGrade.B,
        total_pieces=total,
        retail_price_per_piece_pkr=2_000,
        lot_price_pkr=50_000,
        min_order_pieces=total,
        stock_city="Lahore",
        status=status,
        visibility=Visibility.PRIVATE,
        approved_at=None,
    )
    db.add(lot)
    db.flush()
    for size, count in sizes.items():
        db.add(
            ManifestLine(lot_id=lot.id, brand_id=brand_id, size=size, color="black", pieces=count)
        )
    db.commit()
    return lot


def suggestion_payload(**overrides: object) -> dict[str, object]:
    base: dict[str, object] = {
        "suggested_discount_percent_low": 60,
        "suggested_discount_percent_high": 70,
        "expected_days_to_sell_low": 14,
        "expected_days_to_sell_high": 45,
        "reasoning": "Grade B, one season old, size curve concentrated in medium.",
        "comparable_lot_ids": [],
        "confidence": 0.5,
        "based_on_rules_only": True,
    }
    base.update(overrides)
    return base


def stub(db: Session, lot: Lot, tmp_path, monkeypatch, content: dict) -> None:  # type: ignore[no-untyped-def]
    """Record the reply for exactly the call suggest() will make."""
    from sqlalchemy import select

    from khazana.models import BrandPolicy

    monkeypatch.setattr(client, "FIXTURE_DIR", tmp_path)
    policy = db.scalars(select(BrandPolicy).where(BrandPolicy.brand_id == lot.brand_id)).one()
    cat = db.get(Category, lot.category_id)
    prompt = prompts.load(feature.PROMPT)
    user_text = prompt.render(
        category=cat.name if cat else "unknown",
        season=lot.season or "not stated",
        condition_grade=lot.condition_grade.value,
        total_pieces=lot.total_pieces,
        size_spread=feature._size_spread(db, lot),
        retail_price=lot.retail_price_per_piece_pkr,
        lot_price=lot.lot_price_pkr,
        current_discount=round(lot.discount_percent),
        age_days=feature._age_days(lot),
        title=(lot.title or "")[:200],
        min_discount=float(policy.min_discount_percent),
        max_discount=float(policy.max_discount_percent),
        min_lot_value=policy.min_lot_value_pkr,
        comparables=feature.render_comparables(db, feature.find_comparables(db, lot)),
    )
    key = client.fixture_key(
        feature="pricing",
        prompt_name=prompt.name,
        prompt_version=prompt.version,
        user_text=user_text,
        images=0,
    )
    path = tmp_path / "pricing" / f"{key}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "model": "claude-opus-5-5",
                "content": content,
                "usage": {"input_tokens": 1800, "output_tokens": 260},
            }
        ),
        encoding="utf-8",
    )


class TestClamping:
    def _policy(self, db: Session, brand_id: str, low: float, high: float):  # type: ignore[no-untyped-def]
        from sqlalchemy import select

        from khazana.models import BrandPolicy

        policy = db.scalars(select(BrandPolicy).where(BrandPolicy.brand_id == brand_id)).one()
        policy.min_discount_percent = low
        policy.max_discount_percent = high
        db.commit()
        return policy

    def test_a_suggestion_inside_the_band_is_untouched(self, db: Session, two_brands) -> None:  # type: ignore[no-untyped-def]
        (brand, _), _ = two_brands
        policy = self._policy(db, brand.id, 50, 85)
        suggestion = PriceSuggestion(**suggestion_payload())  # type: ignore[arg-type]

        held, clamped, note = feature.clamp_to_policy(suggestion, policy)

        assert not clamped
        assert note is None
        assert held.suggested_discount_percent_low == 60

    def test_a_suggestion_above_the_band_is_held_inside(self, db: Session, two_brands) -> None:  # type: ignore[no-untyped-def]
        """The band is a commercial decision the brand already made.

        A deeper discount is not a better price, it is a broken promise, so
        this is enforced in code rather than left to a prompt rule.
        """
        (brand, _), _ = two_brands
        policy = self._policy(db, brand.id, 40, 65)
        suggestion = PriceSuggestion(
            **suggestion_payload(
                suggested_discount_percent_low=70, suggested_discount_percent_high=90
            )  # type: ignore[arg-type]
        )

        held, clamped, note = feature.clamp_to_policy(suggestion, policy)

        assert clamped
        assert held.suggested_discount_percent_low == 65
        assert held.suggested_discount_percent_high == 65
        assert note is not None
        assert "held" in note

    def test_a_suggestion_below_the_band_is_raised_into_it(self, db: Session, two_brands) -> None:  # type: ignore[no-untyped-def]
        (brand, _), _ = two_brands
        policy = self._policy(db, brand.id, 55, 80)
        suggestion = PriceSuggestion(
            **suggestion_payload(
                suggested_discount_percent_low=10, suggested_discount_percent_high=30
            )  # type: ignore[arg-type]
        )

        held, clamped, _note = feature.clamp_to_policy(suggestion, policy)

        assert clamped
        assert held.suggested_discount_percent_low == 55
        assert held.suggested_discount_percent_high == 55


class TestComparables:
    def test_only_lots_with_a_completed_order_count(
        self, db: Session, two_brands, category
    ) -> None:  # type: ignore[no-untyped-def]
        """A lot marked sold with no completed order proves nothing.

        It is the most tempting wrong signal in this dataset, because the
        status field is right there and looks authoritative.
        """
        (brand, owner), _ = two_brands
        target = make_lot(db, brand.id, category.id, code="LOT-TARGET")
        # Marked sold, but no order was ever completed against it. The status
        # field looks authoritative and proves nothing.
        make_lot(db, brand.id, category.id, code="LOT-NOORDER", status=LotStatus.SOLD)
        really_sold = make_lot(db, brand.id, category.id, code="LOT-SOLD")

        db.add(
            Order(
                order_code="ORD-1",
                lot_id=really_sold.id,
                brand_id=brand.id,
                buyer_user_id=owner.id,
                pieces=100,
                unit_price_pkr=500,
                subtotal_pkr=50_000,
                shipping_pkr=0,
                total_pkr=50_000,
                commission_percent=15,
                commission_pkr=7_500,
                brand_payout_pkr=42_500,
                status=OrderStatus.CONFIRMED,
                delivery_city="Multan",
                delivery_address="Shop 1",
                delivery_phone="03001234567",
            )
        )
        db.commit()

        found = feature.find_comparables(db, target)
        codes = {row.lot_code for row in found}

        assert "LOT-SOLD" in codes
        assert "LOT-NOORDER" not in codes
        assert "LOT-TARGET" not in codes

    def test_no_comparables_says_so_plainly(self, db: Session, two_brands, category) -> None:  # type: ignore[no-untyped-def]
        (brand, _), _ = two_brands
        lot = make_lot(db, brand.id, category.id)
        rendered = feature.render_comparables(db, feature.find_comparables(db, lot))
        assert "no evidence" in rendered.lower()


class TestSizeSpread:
    def test_a_concentrated_curve_is_called_out(self, db: Session, two_brands, category) -> None:  # type: ignore[no-untyped-def]
        """A lot that is mostly one size is close to worthless in bulk.

        It drives clearance more than people expect, so the model is told the
        shape rather than left to infer it from a total.
        """
        (brand, _), _ = two_brands
        lot = make_lot(db, brand.id, category.id, sizes={"M": 90, "S": 10})
        assert "concentrated in one size" in feature._size_spread(db, lot)

    def test_a_balanced_curve_is_described_as_such(self, db: Session, two_brands, category) -> None:  # type: ignore[no-untyped-def]
        (brand, _), _ = two_brands
        lot = make_lot(db, brand.id, category.id, sizes={"S": 25, "M": 30, "L": 25, "XL": 20})
        assert "reasonably balanced" in feature._size_spread(db, lot)

    def test_a_lot_with_no_manifest_does_not_crash(self, db: Session, two_brands, category) -> None:  # type: ignore[no-untyped-def]
        (brand, _), _ = two_brands
        lot = Lot(
            lot_code="LOT-EMPTY",
            brand_id=brand.id,
            category_id=category.id,
            title="x",
            condition_grade=ConditionGrade.A,
            total_pieces=10,
            retail_price_per_piece_pkr=100,
            lot_price_pkr=500,
            min_order_pieces=10,
            stock_city="Lahore",
            status=LotStatus.DRAFT,
            visibility=Visibility.PRIVATE,
        )
        db.add(lot)
        db.commit()
        assert feature._size_spread(db, lot) == "no manifest recorded"


class TestSuggest:
    def test_a_suggestion_with_no_history_is_labelled_rules_based(
        self, db: Session, two_brands, category, tmp_path, monkeypatch
    ) -> None:  # type: ignore[no-untyped-def]
        """The honesty rule, enforced rather than requested.

        The model is asked to set this flag. It is also set here, because the
        interface label depends on it and a wrong label means a brand takes a
        number more seriously than the evidence deserves.
        """
        (brand, _), _ = two_brands
        lot = make_lot(db, brand.id, category.id)
        stub(
            db,
            lot,
            tmp_path,
            monkeypatch,
            suggestion_payload(based_on_rules_only=False, confidence=0.95),
        )

        outcome = feature.suggest(db, lot.id)

        assert outcome.comparables_used == 0
        assert outcome.suggestion.based_on_rules_only is True
        assert outcome.honest_about_evidence

    def test_the_discount_band_converts_to_money_outside_the_model(
        self, db: Session, two_brands, category, tmp_path, monkeypatch
    ) -> None:  # type: ignore[no-untyped-def]
        """The model never sees or states a rupee figure."""
        (brand, _), _ = two_brands
        lot = make_lot(db, brand.id, category.id)
        stub(db, lot, tmp_path, monkeypatch, suggestion_payload())

        outcome = feature.suggest(db, lot.id)
        retail_total = lot.retail_price_per_piece_pkr * lot.total_pieces
        low, high = outcome.price_range_pkr(retail_total)

        assert retail_total == 200_000
        assert low == 60_000  # 70 percent off
        assert high == 80_000  # 60 percent off
        assert low < high

    def test_a_missing_lot_is_a_clear_error(self, db: Session) -> None:
        with pytest.raises(NotFound):
            feature.suggest(db, "no-such-lot")

    def test_a_brand_with_no_policy_is_refused(self, db: Session, two_brands, category) -> None:  # type: ignore[no-untyped-def]
        from khazana.core.errors import ValidationFailed
        from khazana.models import BrandPolicy

        (brand, _), _ = two_brands
        lot = make_lot(db, brand.id, category.id)
        db.delete(db.query(BrandPolicy).filter_by(brand_id=brand.id).one())
        db.commit()

        with pytest.raises(ValidationFailed, match="no policy row"):
            feature.suggest(db, lot.id)
