"""The published API description is complete, consistent and current.

docs/openapi.json and docs/api-reference.md are generated from the code. This
fails when either is stale, and when the spec disagrees with how the API
actually behaves: an operation the route walk proves is protected must say
so, and every refusal must point at the one error shape.
"""

from __future__ import annotations

import re
from pathlib import Path

from khazana.api.openapi import TAGS, render_json, render_markdown
from khazana.main import create_app
from test_route_auth import PUBLIC

DOCS = Path(__file__).resolve().parents[3] / "docs"
SPEC = create_app().openapi()
OPERATIONS = [
    (method.upper(), path, operation)
    for path, item in SPEC["paths"].items()
    for method, operation in item.items()
]


def test_every_protected_operation_declares_the_bearer_scheme() -> None:
    assert SPEC["components"]["securitySchemes"]["bearer"]["scheme"] == "bearer"
    for method, path, operation in OPERATIONS:
        if (method, path) not in PUBLIC:
            assert operation.get("security") == [{"bearer": []}], f"{method} {path}"
        names = [p["name"].lower() for p in operation.get("parameters", [])]
        assert "authorization" not in names, f"{method} {path} lists the token as a parameter"


def test_only_the_known_public_operations_are_open() -> None:
    open_ops = {
        (method, path) for method, path, operation in OPERATIONS if not operation.get("security")
    }
    assert open_ops <= PUBLIC, sorted(open_ops - PUBLIC)


def test_every_operation_documents_the_error_shape() -> None:
    for method, path, operation in OPERATIONS:
        schema = operation["responses"]["4XX"]["content"]["application/json"]["schema"]
        assert schema == {"$ref": "#/components/schemas/ErrorBody"}, f"{method} {path}"


def test_names_follow_the_conventions() -> None:
    ids = [operation["operationId"] for _, _, operation in OPERATIONS]
    assert len(ids) == len(set(ids)), "operationIds are unique"
    for operation_id in ids:
        assert re.fullmatch(r"[a-z][a-z0-9_]*", operation_id), operation_id
    used = {operation["tags"][0] for _, _, operation in OPERATIONS}
    for tag in used:
        assert re.fullmatch(r"[a-z][a-z-]*", tag), f"tag {tag!r} is not kebab case"
        assert tag in TAGS, f"tag {tag!r} has no description in api/openapi.py"


def test_the_published_files_match_the_code() -> None:
    hint = "run: python scripts/generate-api-reference.py"
    assert (DOCS / "openapi.json").read_text(encoding="utf-8") == render_json(SPEC), hint
    assert (DOCS / "api-reference.md").read_text(encoding="utf-8") == render_markdown(SPEC), hint
