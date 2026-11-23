"""The published API description: the OpenAPI spec and its Markdown reference.

FastAPI generates the spec from the routes. Three things it cannot know are
added here, after generation:

- **Authentication.** Every protected route reads a bearer token from the
  ``Authorization`` header, which FastAPI lists as an ordinary parameter. The
  spec declares a ``bearer`` security scheme instead, so a client generator
  knows how to sign requests.
- **Errors.** Every error the API returns has the same shape, ``{code,
  message}``. It is declared once as ``ErrorBody`` and attached to every
  operation as its 4XX response.
- **Tag descriptions**, so the reference reads as sections, not a list.

``docs/openapi.json`` and ``docs/api-reference.md`` are generated from this
by ``scripts/generate-api-reference.py``, and a test fails when either no
longer matches the code.
"""

from __future__ import annotations

import json
from typing import Any

from fastapi import FastAPI
from fastapi.openapi.utils import get_openapi

TAGS: dict[str, str] = {
    "ops": "Health, readiness and the AI gateway status. Open without sign in.",
    "auth": "Sign in with a one time code, refresh a session, sign out everywhere.",
    "brands": "Brand profiles, staff, verification documents and policy.",
    "catalog": "Lots: creating, photographs, manifests, approval and the buyer catalogue.",
    "search": "Catalogue search, saved searches, photo search and recommendations.",
    "orders": "Cart, checkout, the order lifecycle, disputes and returns.",
    "payments": "Starting a payment, provider callbacks and brand payouts.",
    "logistics": "Shipments, pickups, labels, tracking and courier callbacks.",
    "pools": "Committee pools: several shops buying one lot together.",
    "bargaining": "Negotiating a price inside the brand's band, and the markdown agent.",
    "resell-kits": "Captions, posts and price tags for a paid order.",
    "assistant": "The buyer and brand assistants, on the web and on WhatsApp.",
    "ai": "The AI features a brand drives directly: listing drafts, manifests, pricing, risk.",
    "forecasts": "Demand forecasts and production warnings for a brand.",
    "redirections": "Sending unsold stock to upcycling or donation partners.",
    "analytics": "Brand and platform reports.",
    "resellers": "Reseller profiles and verification.",
    "admin": "Moderation, payments, payouts, disputes, settings and scheduled jobs.",
}

ERROR_BODY: dict[str, Any] = {
    "type": "object",
    "title": "ErrorBody",
    "required": ["code", "message"],
    "properties": {
        "code": {
            "type": "string",
            "description": "A stable, machine readable reason, such as `not_found`, "
            "`conflict`, `rate_limited` or `too_large`.",
        },
        "message": {
            "type": "string",
            "description": "A sentence a person can act on, in English.",
        },
    },
}


def build(app: FastAPI) -> dict[str, Any]:
    """The spec FastAPI generates, with authentication, errors and tags added."""
    spec = get_openapi(
        title=app.title,
        version=app.version,
        description=app.description,
        routes=app.routes,
        tags=[{"name": name, "description": text} for name, text in TAGS.items()],
    )
    components = spec.setdefault("components", {})
    components.setdefault("schemas", {})["ErrorBody"] = ERROR_BODY
    components["securitySchemes"] = {
        "bearer": {
            "type": "http",
            "scheme": "bearer",
            "description": "The access token from `POST /auth/otp/verify` or "
            "`POST /auth/refresh`. It lasts an hour; refresh before it ends.",
        }
    }
    for path_item in spec.get("paths", {}).values():
        for operation in path_item.values():
            parameters = operation.get("parameters", [])
            signed = [p for p in parameters if p.get("name", "").lower() == "authorization"]
            if signed:
                operation["parameters"] = [p for p in parameters if p not in signed]
                if not operation["parameters"]:
                    del operation["parameters"]
                operation["security"] = [{"bearer": []}]
            operation.setdefault("responses", {})["4XX"] = {
                "description": "The request was refused. The body says why.",
                "content": {
                    "application/json": {"schema": {"$ref": "#/components/schemas/ErrorBody"}}
                },
            }
    return spec


def install(app: FastAPI) -> None:
    """Serve the finished spec at /openapi.json and in the interactive docs."""

    def _openapi() -> dict[str, Any]:
        if app.openapi_schema is None:
            app.openapi_schema = build(app)
        return app.openapi_schema

    app.openapi = _openapi  # type: ignore[method-assign]


def render_json(spec: dict[str, Any]) -> str:
    # One space of indent: readable in a diff, and under the 512 KB limit the
    # pre-commit hook puts on any added file, which two spaces passed.
    return json.dumps(spec, indent=1, sort_keys=True, ensure_ascii=False) + "\n"


def render_markdown(spec: dict[str, Any]) -> str:
    """A readable reference: one section per tag, one entry per operation."""
    lines = [
        "# API reference",
        "",
        "Generated from the code by `scripts/generate-api-reference.py`; do not edit",
        "by hand. The machine readable version is [`openapi.json`](openapi.json), and",
        "a running API serves the same spec at `/openapi.json` with interactive docs",
        "at `/docs`.",
        "",
        f"Version {spec['info']['version']}. {len(_operations(spec))} operations.",
        "",
        "## Conventions",
        "",
        "- **Authentication.** Send `Authorization: Bearer <access token>` on every",
        "  operation marked *signed in*. Tokens come from `POST /auth/otp/verify` and",
        "  last an hour; `POST /auth/refresh` exchanges the refresh token for a new",
        "  pair. A refresh token works once.",
        '- **Errors.** Every refusal is a 4XX with `{"code": ..., "message": ...}`.',
        "  `message` is meant for a person; `code` is stable for code to branch on.",
        "- **Money** is whole rupees as integers, in fields ending `_pkr`.",
        "- **Times** are ISO 8601 in UTC.",
        "",
        "## Contents",
        "",
    ]
    by_tag: dict[str, list[tuple[str, str, dict[str, Any]]]] = {}
    for path, method, operation in _operations(spec):
        by_tag.setdefault(operation.get("tags", ["other"])[0], []).append((path, method, operation))
    ordered = [name for name in TAGS if name in by_tag] + sorted(set(by_tag) - set(TAGS))
    for name in ordered:
        lines.append(f"- [{name}](#{name}) ({len(by_tag[name])})")
    lines.append("")
    for name in ordered:
        lines += [f"## {name}", ""]
        if name in TAGS:
            lines += [TAGS[name], ""]
        lines += ["| Method | Path | Summary | Access |", "| --- | --- | --- | --- |"]
        for path, method, operation in by_tag[name]:
            access = "signed in" if operation.get("security") else "open"
            summary = operation.get("summary", "").replace("|", "\\|")
            lines.append(f"| `{method.upper()}` | `{path}` | {summary} | {access} |")
        lines.append("")
        for path, method, operation in by_tag[name]:
            lines += [f"### `{method.upper()} {path}`", ""]
            lines.append(f"`{operation['operationId']}`")
            lines.append("")
            description = (operation.get("description") or operation.get("summary") or "").strip()
            if description:
                lines += [description, ""]
            parameters = operation.get("parameters", [])
            if parameters:
                lines += ["| Parameter | In | Required |", "| --- | --- | --- |"]
                for parameter in parameters:
                    required = "yes" if parameter.get("required") else "no"
                    lines.append(f"| `{parameter['name']}` | {parameter['in']} | {required} |")
                lines.append("")
            body = _schema_name(operation.get("requestBody", {}))
            if body:
                lines += [f"Request body: `{body}`", ""]
            ok = next((code for code in operation["responses"] if code.startswith("2")), None)
            if ok:
                returned = _schema_name(operation["responses"][ok])
                lines += [f"Returns `{ok}`" + (f" with `{returned}`." if returned else "."), ""]
    return "\n".join(lines).rstrip() + "\n"


def _operations(spec: dict[str, Any]) -> list[tuple[str, str, dict[str, Any]]]:
    return [
        (path, method, operation)
        for path, item in spec.get("paths", {}).items()
        for method, operation in item.items()
    ]


def _schema_name(holder: dict[str, Any]) -> str | None:
    for content in holder.get("content", {}).values():
        schema = content.get("schema", {})
        if "$ref" in schema:
            return str(schema["$ref"]).rsplit("/", 1)[-1]
        if schema.get("type") == "array" and "$ref" in schema.get("items", {}):
            return "list of " + str(schema["items"]["$ref"]).rsplit("/", 1)[-1]
    return None
