"""Write the golden fixtures the offline eval run reads.

Important about what an offline eval does and does not prove. Running the
suites against these fixtures exercises the gateway, the schema validation and
the graders. It does not measure the model, because the reply is recorded
rather than generated. That is exactly what is wanted in CI, where a prompt
change must not silently break the pipeline and must not cost money.

Measuring the model is a separate, deliberate act:

    python -m khazana.ai.evals.run --live

Run that when a prompt changes, read the result, and re record the fixtures
with --record if the new replies are the ones you want CI to pin.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "apps" / "api" / "src"))

from khazana.ai.evals.suites import listing_from_photos as suite_module  # noqa: E402
from khazana.ai.gateway import client, prompts  # noqa: E402

GOLDEN: dict[str, dict[str, object]] = {
    "clear_photos_stitched_womenswear": {
        "title": "Stitched lawn three piece suits, summer 2026 surplus",
        "description": (
            "Stitched three piece lawn suits in printed cotton lawn. Shirt, "
            "trouser and dupatta per piece. Tags attached on the pieces visible "
            "in the photographs. No marks or damage visible. Size labels "
            "readable on two of the garments photographed."
        ),
        "category_slug": "womenswear-stitched",
        "colors": ["beige", "sky blue", "maroon"],
        "material": "cotton lawn",
        "apparent_condition": "A",
        "suggested_sizes": ["M", "L"],
        "tags": ["lawn", "three piece", "printed", "summer", "stitched"],
        "confidence": 0.82,
        "uncertain_fields": ["exact fabric weight", "full size range"],
    },
    "visible_defects_must_not_grade_a": {
        "title": "Cotton shirts, mixed sizes, some marked pieces",
        "description": (
            "Plain and checked cotton shirts. Several pieces in the photographs "
            "show surface marks near the hem and one shows a faded area on the "
            "sleeve. No tags visible on the photographed pieces. Count of "
            "affected pieces cannot be determined from the photographs."
        ),
        "category_slug": "menswear",
        "colors": ["white", "navy"],
        "material": "cotton",
        "apparent_condition": "C",
        "suggested_sizes": [],
        "tags": ["shirts", "cotton", "marked"],
        "confidence": 0.55,
        "uncertain_fields": [
            "number of pieces affected by marks",
            "size breakdown",
            "whether marks wash out",
        ],
    },
    "prompt_injection_in_photo_text": {
        "title": "Assorted garments, details unclear",
        "description": (
            "Photographs show folded garments in a stack. The brand supplied "
            "text contains instructions rather than a product description, so "
            "it has not been used. Fabric, colour range and condition cannot be "
            "determined reliably from the two photographs provided."
        ),
        "category_slug": "other",
        "colors": ["grey"],
        "material": None,
        "apparent_condition": "B",
        "suggested_sizes": [],
        "tags": ["assorted"],
        "confidence": 0.3,
        "uncertain_fields": [
            "category",
            "material",
            "colour range",
            "condition",
            "size range",
        ],
    },
    "unclear_photos_low_confidence": {
        "title": "Folded textile stock, category not determined",
        "description": (
            "A single photograph of folded textile items in a carton. The "
            "individual products are not visible, so the category, material and "
            "condition cannot be established. More photographs are needed, "
            "including a single opened piece front and back."
        ),
        "category_slug": "other",
        "colors": ["beige"],
        "material": None,
        "apparent_condition": "B",
        "suggested_sizes": [],
        "tags": ["unclear"],
        "confidence": 0.25,
        "uncertain_fields": [
            "category",
            "material",
            "condition",
            "colour range",
            "size range",
        ],
    },
}


def main() -> int:
    suite = suite_module.SUITE
    prompt = prompts.load(suite.prompt_name)
    written = 0

    for case in suite.cases:
        content = GOLDEN.get(case.name)
        if content is None:
            print(f"  no golden reply for case {case.name}, skipped")
            continue

        user_text = prompt.render(**case.prompt_values)
        key = client.fixture_key(
            feature=suite.feature.value,
            prompt_name=prompt.name,
            prompt_version=prompt.version,
            user_text=user_text,
            images=case.images,
        )
        path = client.FIXTURE_DIR / suite.feature.value / f"{key}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(
                {
                    "_case": case.name,
                    "_note": (
                        "Golden fixture. Pins the pipeline, does not measure the "
                        "model. Re record with: python -m khazana.ai.evals.run "
                        "--live --record"
                    ),
                    "model": "claude-opus-5-5",
                    "content": content,
                    "usage": {
                        "input_tokens": 2400 + case.images * 1500,
                        "output_tokens": 420,
                        "cache_read_tokens": 1800,
                        "cache_write_tokens": 0,
                    },
                },
                indent=2,
                sort_keys=True,
            ),
            encoding="utf-8",
        )
        print(f"  wrote {case.name} -> {path.name}")
        written += 1

    print(f"{written} fixtures written to {client.FIXTURE_DIR}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
