"""Every AI feature that calls a model has an eval suite.

CLAUDE.md requires an eval for every AI feature, written first. This reads the
source for every ``run_feature`` call and checks each feature it names has at
least one suite, so a feature cannot ship with no eval at all.
"""

from __future__ import annotations

import re
from pathlib import Path

from khazana.ai.evals.run import discover_suites

SRC = Path(__file__).resolve().parent.parent / "src" / "khazana"


def test_every_feature_that_calls_a_model_has_a_suite() -> None:
    used: set[str] = set()
    for path in SRC.rglob("*.py"):
        if "evals" in path.parts:
            continue
        text = path.read_text(encoding="utf-8")
        for call in re.finditer(r"run_feature\(\s*db,\s*AiFeature\.([A-Z_]+)", text):
            used.add(call.group(1).lower())
    covered = {suite.feature.value for suite in discover_suites(None)}
    assert used, "no run_feature calls found; the pattern no longer matches the code"
    assert used <= covered, f"features with no eval suite: {sorted(used - covered)}"
