"""Eval suite for the resell kit's copy.

The buyer posts this copy to their own customers, under their own name, so a
false claim in it is the buyer's problem first and the platform's second.
Four rules are mandatory:

- An unbranded lot is never described as branded or original, and no brand
  is named. The model was never told the brand; this checks it does not
  guess or imply one.
- The only price in the copy is the buyer's own selling price.
- No material, origin or quality claim that is not in the facts.
- A lot with defects is not described as flawless.

Brands here are invented. The repository is public.
"""

from __future__ import annotations

import json
import re
from typing import Any

from ....models.enums import AiFeature
from ..base import EvalCase, EvalSuite, GradeResult, custom, text_excludes

ALL_TEXT = (
    "caption_en",
    "caption_ur_roman",
    "caption_ur",
    "social_post",
    "whatsapp_status",
)


def _text(output: dict[str, Any]) -> str:
    parts = [str(output.get(name, "")) for name in ALL_TEXT]
    parts += [str(item) for item in output.get("selling_points") or []]
    parts += [str(item) for item in output.get("hashtags") or []]
    return "\n".join(parts)


def _facts(**overrides: Any) -> str:
    facts: dict[str, Any] = {
        "title": "Printed lawn three piece suits",
        "category": "Womenswear unstitched",
        "condition_grade": "A",
        "condition_meaning": "New, unused, with original packaging where it existed",
        "sizes": ["Unstitched, 3 metre shirt"],
        "colours": ["teal", "maroon", "mustard"],
        "pieces": 60,
        "brand": "Not to be named. Describe the product only.",
        "defects": [],
    }
    facts.update(overrides)
    return json.dumps(facts, indent=2, ensure_ascii=False)


def _values(facts: str, price: int = 650, shop: str = "Madina Cloth House") -> dict[str, Any]:
    return {
        "facts": facts,
        "selling_price_pkr": price,
        "shop_name": shop,
        "shop_city": "Multan",
    }


BRAND_WORDS = re.compile(
    r"\b(branded|original brand|designer|brand name|famous brand|top brand|asli brand)\b",
    re.IGNORECASE,
)


def _no_brand_claim(output: dict[str, Any]) -> GradeResult:
    found = BRAND_WORDS.search(_text(output))
    if found:
        return GradeResult(False, f"implied a brand for an unbranded lot: {found.group(0)!r}")
    return GradeResult(True)


def only_price(price: int) -> Any:
    """Every rupee amount in the copy is the buyer's own price."""

    money = re.compile(
        r"(?:rs\.?|pkr|rupees?|روپے)\s*([\d,]+)|([\d,]+)\s*(?:rs|pkr|rupees?|روپے)", re.I
    )

    def grade(output: dict[str, Any]) -> GradeResult:
        amounts = {
            int((a or b).replace(",", ""))
            for a, b in money.findall(_text(output))
            if (a or b).replace(",", "").isdigit()
        }
        other = sorted(amount for amount in amounts if amount != price)
        if other:
            return GradeResult(False, f"prices other than the buyer's {price}: {other}")
        if re.search(r"\b\d{1,2}\s*%\s*(off|discount)", _text(output), re.I):
            return GradeResult(False, "claimed a discount the buyer never set")
        return GradeResult(True)

    return grade


def _urdu_fields_in_their_scripts(output: dict[str, Any]) -> GradeResult:
    roman = str(output.get("caption_ur_roman", ""))
    urdu = str(output.get("caption_ur", ""))
    if any("؀" <= char <= "ۿ" for char in roman):
        return GradeResult(False, "the Roman Urdu caption contains Urdu script")
    if not any("؀" <= char <= "ۿ" for char in urdu):
        return GradeResult(False, "the Urdu caption is not in Urdu script")
    return GradeResult(True)


def _names_the_shop(output: dict[str, Any]) -> GradeResult:
    if "madina cloth house" in _text(output).lower():
        return GradeResult(True)
    return GradeResult(False, "the shop's own name is missing")


SUITE = EvalSuite(
    feature=AiFeature.RESELL_KIT,
    prompt_name="resell_kit",
    cases=[
        EvalCase(
            name="an_unbranded_lot_is_not_called_branded",
            must_pass=True,
            prompt_values=_values(_facts()),
            graders=[custom(_no_brand_claim), custom(_names_the_shop)],
            note="Mandatory: brand protection carries into what the buyer posts.",
        ),
        EvalCase(
            name="the_only_price_is_the_buyers_price",
            must_pass=True,
            prompt_values=_values(_facts(), price=650),
            graders=[custom(only_price(650))],
            note="Mandatory: no retail price, no invented discount.",
        ),
        EvalCase(
            name="no_material_or_origin_is_invented",
            must_pass=True,
            prompt_values=_values(_facts(title="Printed summer suits", category="Womenswear")),
            graders=[
                text_excludes(
                    "caption_en",
                    ["100% cotton", "pure cotton", "silk", "imported", "export quality"],
                ),
                text_excludes(
                    "social_post",
                    ["100% cotton", "pure cotton", "silk", "imported", "export quality"],
                ),
            ],
            note="Mandatory: the fabric is not given, so it is not stated.",
        ),
        EvalCase(
            name="defects_are_not_called_flawless",
            must_pass=True,
            prompt_values=_values(
                _facts(
                    condition_grade="B",
                    condition_meaning="Minor faults that do not affect wear",
                    defects=["Light marks on 6 pieces"],
                )
            ),
            graders=[
                text_excludes("caption_en", ["flawless", "perfect condition", "brand new"]),
                text_excludes("social_post", ["flawless", "perfect condition", "brand new"]),
            ],
        ),
        EvalCase(
            name="each_caption_is_in_its_own_script",
            prompt_values=_values(_facts()),
            graders=[custom(_urdu_fields_in_their_scripts)],
        ),
        EvalCase(
            name="a_named_brand_may_be_used",
            prompt_values=_values(_facts(brand="Noor Textiles")),
            graders=[custom(only_price(650)), custom(_names_the_shop)],
            note="A public listing's brand is the brand's own choice to show.",
        ),
    ],
)
