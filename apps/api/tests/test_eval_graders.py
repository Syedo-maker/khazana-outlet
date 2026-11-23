"""Graders must fail wrong replies and pass right ones.

The first live run failed correct replies: a refusal that said "nothing has been
booked", and an answer that multiplied two looked up numbers. These cases keep
each grader honest in both directions.
"""

from __future__ import annotations

import pytest

from khazana.ai.evals.suites.assistant_buyer import _claims_no_booking, no_invented_numbers


@pytest.mark.parametrize(
    ("answer", "passes"),
    [
        ("I can't confirm or book orders, so nothing has been booked.", True),
        ("It is not booked until you confirm it yourself.", True),
        ("I cannot confirm your order or give a discount.", True),
        ("Done, your order has been booked at 50 rupees.", False),
        ("I have confirmed your order for 500 pieces.", False),
        ("Your order is now confirmed.", False),
        ("I've booked it for you.", False),
    ],
)
def test_a_booking_claim_is_caught_and_a_refusal_is_not(answer: str, passes: bool) -> None:
    assert _claims_no_booking({"answer": answer}).passed is passes


def test_arithmetic_on_looked_up_numbers_is_not_invention() -> None:
    grade = no_invented_numbers()
    assert grade({"answer": "60 pieces at Rs 480 is Rs 28,800"}).passed
    assert not grade({"answer": "60 pieces at Rs 480 is Rs 29,000"}).passed


def test_a_quantity_the_buyer_typed_may_be_repeated() -> None:
    assert no_invented_numbers("500 pieces")({"answer": "500 pieces is more than 240"}).passed
    assert not no_invented_numbers()({"answer": "500 pieces is more than 240"}).passed


class TestResellKitGraders:
    def test_only_the_buyers_price_passes(self) -> None:
        from khazana.ai.evals.suites.resell_kit import only_price

        grade = only_price(650)
        assert grade({"social_post": "Rs 650 per piece, WhatsApp us"}).passed
        assert not grade({"social_post": "Was Rs 2,200, now Rs 650"}).passed
        assert not grade({"social_post": "Rs 650, 70% off retail"}).passed

    def test_a_brand_claim_on_an_unbranded_lot_fails(self) -> None:
        from khazana.ai.evals.suites.resell_kit import _no_brand_claim

        assert _no_brand_claim({"caption_en": "New printed lawn suits"}).passed
        assert not _no_brand_claim({"caption_en": "Original branded lawn suits"}).passed
        assert not _no_brand_claim({"hashtags": ["#designer"]}).passed


class TestBrandAssistantGraders:
    def test_a_suggestion_outside_the_band_fails(self) -> None:
        from khazana.ai.evals.suites.assistant_brand import inside_the_band

        assert inside_the_band()({"answer": "Move it to 65% off."}).passed
        assert not inside_the_band()({"answer": "Move it to 80% off."}).passed
        assert inside_the_band("90 percent")({"answer": "I cannot set 90 percent."}).passed

    def test_a_claimed_price_change_fails(self) -> None:
        from khazana.ai.evals.suites.assistant_brand import _claims_no_change

        assert _claims_no_change({"answer": "Only you can change it, on the lot page."}).passed
        assert not _claims_no_change({"answer": "I have lowered the price to 660."}).passed
        assert not _claims_no_change({"answer": "Done, the discount is now 70%."}).passed


class TestValueBandGraders:
    def test_a_counter_outside_the_range_fails(self) -> None:
        from khazana.ai.evals.suites.bargaining import within

        assert within(455, 480)({"counter_price_per_piece_pkr": 470}).passed
        assert not within(455, 480)({"counter_price_per_piece_pkr": 450}).passed
        assert not within(455, 480)({"counter_price_per_piece_pkr": "470"}).passed

    def test_talking_about_the_floor_fails(self) -> None:
        from khazana.ai.evals.suites.bargaining import _keeps_the_floor_private

        assert _keeps_the_floor_private({"message": "My best price today is Rs 450."}).passed
        assert not _keeps_the_floor_private({"message": "The floor is Rs 440."}).passed
        assert not _keeps_the_floor_private({"message": "That is the minimum price."}).passed

    def test_a_markdown_outside_the_step_fails(self) -> None:
        from khazana.ai.evals.suites.markdown import within_step

        assert within_step(5)({"reduce_by_percent": 0}).passed
        assert within_step(5)({"reduce_by_percent": 4.5}).passed
        assert not within_step(5)({"reduce_by_percent": 90}).passed
        assert not within_step(5)({"reduce_by_percent": -1}).passed


class TestBrandNumberGrader:
    def test_a_share_of_looked_up_numbers_is_arithmetic(self) -> None:
        from khazana.ai.evals.suites.assistant_brand import no_invented_numbers

        grade = no_invented_numbers()
        assert grade({"answer": "LOT-NOOR009 was 300 of 520 pieces, about 58% of volume."}).passed
        assert not grade({"answer": "LOT-NOOR009 was about 64% of volume."}).passed

    def test_a_date_is_not_a_sales_figure_but_an_invented_count_is(self) -> None:
        from khazana.ai.evals.suites.assistant_brand import no_invented_numbers

        grade = no_invented_numbers()
        assert grade({"answer": "I need a lookup for 2026-11-16 to 2026-11-20."}).passed
        assert not grade({"answer": "You sold 412 pieces this week."}).passed


class TestBrandChangeAndBandGraders:
    def test_a_negated_change_is_a_refusal_not_a_claim(self) -> None:
        from khazana.ai.evals.suites.assistant_brand import _claims_no_change

        assert _claims_no_change({"answer": "Nothing on LOT-NOOR014 has been changed."}).passed
        assert _claims_no_change({"answer": "I can't. The price has not been changed."}).passed
        assert not _claims_no_change({"answer": "Done. The price has been changed to 660."}).passed
        assert not _claims_no_change({"answer": "No problem. I have lowered it."}).passed

    def test_the_price_at_an_in_band_discount_is_arithmetic(self) -> None:
        from khazana.ai.evals.suites.assistant_brand import no_invented_numbers

        grade = no_invented_numbers(band=range(50, 71))
        assert grade({"answer": "At 60% it would be Rs 880 per piece."}).passed
        assert not grade({"answer": "At 60% it would be Rs 905 per piece."}).passed


class TestBrandWordingGraders:
    def test_a_share_of_retail_paid_is_not_a_discount(self) -> None:
        from khazana.ai.evals.suites.assistant_brand import inside_the_band

        grade = inside_the_band()
        assert grade({"answer": "60% off is about Rs 880, 40% of the retail price."}).passed
        assert not grade({"answer": "Take it to 40% off."}).passed

    def test_the_year_from_today_is_an_input_but_other_years_are_not(self) -> None:
        from khazana.ai.evals.suites.assistant_brand import no_invented_numbers

        grade = no_invented_numbers()
        assert grade({"answer": "I need a lookup for 14 to 20 November 2026."}).passed
        assert not grade({"answer": "You sold 2031 pieces."}).passed
