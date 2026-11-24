"""Write docs/openapi.json and docs/api-reference.md from the code.

Re run it whenever a route changes:

    python scripts/generate-api-reference.py

tests/test_openapi_contract.py fails when either file no longer matches.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "apps" / "api" / "src"))

from khazana.api.openapi import render_json, render_markdown  # noqa: E402
from khazana.main import create_app  # noqa: E402


def main() -> None:
    spec = create_app().openapi()
    (ROOT / "docs" / "openapi.json").write_text(render_json(spec), encoding="utf-8")
    (ROOT / "docs" / "api-reference.md").write_text(render_markdown(spec), encoding="utf-8")
    print(f"wrote docs/openapi.json and docs/api-reference.md, {len(spec['paths'])} paths")


if __name__ == "__main__":
    main()
