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
