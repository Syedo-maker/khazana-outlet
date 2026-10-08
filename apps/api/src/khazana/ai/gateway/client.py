"""The only place the Anthropic client is constructed.

Two modes.

Live mode calls the API. Offline mode reads a recorded fixture and returns it
without a network call, which is what development, the test suite and CI use.
Offline is the default, so nobody accidentally spends money running the test
suite, and the eval job in CI is free.

Fixtures are keyed by a hash of the request, so recording one is as simple as
running a feature once in live mode with ``record=True``.
"""

from __future__ import annotations

import hashlib
import json
import logging
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ...config import get_settings
from .cost import Usage
from .models import spec_for

logger = logging.getLogger(__name__)

FIXTURE_DIR = Path(__file__).resolve().parent.parent / "evals" / "fixtures"


@dataclass(slots=True)
class ModelReply:
    """What a call returned, independent of which mode produced it."""

    content: dict[str, Any]
    usage: Usage
    model: str
    latency_ms: int
    from_fixture: bool = False
    raw_text: str | None = None


class AiClientError(RuntimeError):
    pass


def fixture_key(
    *, feature: str, prompt_name: str, prompt_version: int, user_text: str, images: int
) -> str:
    """Stable key for a request, so a fixture can be found again.

    The image bytes are not hashed, only the count. Hashing the bytes would
    make a fixture unusable the moment a photograph is recompressed, which
    happens constantly, and the eval set supplies its own images anyway.
    """
    payload = json.dumps(
        {
            "feature": feature,
            "prompt": f"{prompt_name}.v{prompt_version}",
            "user": user_text.strip(),
            "images": images,
        },
        sort_keys=True,
    )
    return hashlib.sha256(payload.encode()).hexdigest()[:32]


def call_model(
    *,
    model: str,
    system: str,
    user_text: str,
    output_schema: dict[str, Any] | None = None,
    images: list[bytes] | None = None,
    effort: str | None = None,
    max_tokens: int = 2_000,
    cache_prefix: bool = True,
    feature: str = "unknown",
    prompt_name: str = "unknown",
    prompt_version: int = 1,
    record: bool = False,
) -> ModelReply:
    """Make one model call, or return the recorded reply for it."""
    settings = get_settings()
    images = images or []
    key = fixture_key(
        feature=feature,
        prompt_name=prompt_name,
        prompt_version=prompt_version,
        user_text=user_text,
        images=len(images),
    )

    if settings.ai_offline:
        return _from_fixture(feature=feature, key=key, model=model)

    if not settings.anthropic_api_key:
        raise AiClientError(
            "ANTHROPIC_API_KEY is not set and AI_OFFLINE is false. Either set the "
            "key or run with AI_OFFLINE=true to use recorded fixtures."
        )

    reply = _call_live(
        model=model,
        system=system,
        user_text=user_text,
        output_schema=output_schema,
        images=images,
        effort=effort,
        max_tokens=max_tokens,
        cache_prefix=cache_prefix,
    )

    if record:
        _save_fixture(feature=feature, key=key, reply=reply)

    return reply


def _call_live(
    *,
    model: str,
    system: str,
    user_text: str,
    output_schema: dict[str, Any] | None,
    images: list[bytes],
    effort: str | None,
    max_tokens: int,
    cache_prefix: bool,
) -> ModelReply:
    import base64

    import anthropic

    settings = get_settings()
    spec = spec_for(model)
    client = anthropic.Anthropic(api_key=settings.anthropic_api_key)

    # Render order for caching is tools, then system, then messages, so the
    # cache breakpoint goes on the last system block and everything variable
    # goes into messages after it.
    system_blocks: list[dict[str, Any]] = [{"type": "text", "text": system}]
    if cache_prefix:
        system_blocks[-1]["cache_control"] = {"type": "ephemeral"}

    content: list[dict[str, Any]] = []
    for raw in images:
        content.append(
            {
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": "image/jpeg",
                    "data": base64.b64encode(raw).decode(),
                },
            }
        )
    content.append({"type": "text", "text": user_text})

    request: dict[str, Any] = {
        "model": model,
        "max_tokens": max_tokens,
        "system": system_blocks,
        "messages": [{"role": "user", "content": content}],
    }

    if output_schema is not None:
        request["output_config"] = {"format": output_schema}

    if effort is not None:
        request.setdefault("output_config", {})
        request["output_config"]["effort"] = effort

    # Opus 5.5 and Sonnet 5.5 always think: sending a thinking block or a
    # token budget to them is rejected. Haiku 4.5 still takes the older form,
    # and this is the only place in the codebase that needs to know.
    if spec.uses_budget_tokens and max_tokens > 2_048:
        request["thinking"] = {"type": "enabled", "budget_tokens": 1_024}

    started = time.perf_counter()
    response = client.messages.create(**request)
    latency_ms = int((time.perf_counter() - started) * 1000)

    stop_reason = getattr(response, "stop_reason", None)
    if stop_reason == "refusal":
        raise AiClientError(
            "The model declined this request. Check the input for anything that "
            "could read as unsafe, and log the stop details."
        )
    if stop_reason == "max_tokens":
        raise AiClientError(
            f"The reply hit the {max_tokens} token ceiling and is truncated. "
            "Raise max_tokens for this route or shorten the input."
        )

    text = _first_text(response)
    usage = Usage(
        input_tokens=getattr(response.usage, "input_tokens", 0) or 0,
        output_tokens=getattr(response.usage, "output_tokens", 0) or 0,
        cache_read_tokens=getattr(response.usage, "cache_read_input_tokens", 0) or 0,
        cache_write_tokens=getattr(response.usage, "cache_creation_input_tokens", 0) or 0,
    )

    if cache_prefix and usage.cache_read_tokens == 0 and usage.cache_write_tokens == 0:
        # A silently broken cache is the single most expensive mistake in this
        # layer, and it produces no error of its own. Say so loudly.
        logger.warning(
            "prompt cache did not engage for model=%s: check that nothing variable "
            "is in the system prefix",
            model,
        )

    return ModelReply(
        content=_parse_json(text),
        usage=usage,
        model=model,
        latency_ms=latency_ms,
        raw_text=text,
    )


def _first_text(response: Any) -> str:
    for block in getattr(response, "content", []):
        if getattr(block, "type", None) == "text":
            return str(getattr(block, "text", ""))
    raise AiClientError("The reply contained no text block.")


def _parse_json(text: str) -> dict[str, Any]:
    """Parse the structured reply.

    Always ``json.loads``, never string matching. Current models vary their
    escaping of Unicode and forward slashes, and a hand rolled parse breaks on
    the first Urdu colour name.
    """
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.split("\n", 1)[1] if "\n" in cleaned else cleaned
        cleaned = cleaned.rsplit("```", 1)[0]
    try:
        parsed = json.loads(cleaned)
    except json.JSONDecodeError as exc:
        raise AiClientError(f"The reply was not valid JSON: {exc}") from exc
    if not isinstance(parsed, dict):
        raise AiClientError("The reply was valid JSON but not an object.")
    return parsed


def _fixture_path(feature: str, key: str) -> Path:
    return FIXTURE_DIR / feature / f"{key}.json"


def _from_fixture(*, feature: str, key: str, model: str) -> ModelReply:
    path = _fixture_path(feature, key)
    if not path.exists():
        raise AiClientError(
            f"No fixture for {feature} at {path.name}. Offline mode cannot invent "
            "a reply. Record one by running this feature once with AI_OFFLINE=false "
            "and record=True, or add the fixture by hand."
        )
    data = json.loads(path.read_text(encoding="utf-8"))
    usage = data.get("usage", {})
    return ModelReply(
        content=data["content"],
        usage=Usage(
            input_tokens=usage.get("input_tokens", 0),
            output_tokens=usage.get("output_tokens", 0),
            cache_read_tokens=usage.get("cache_read_tokens", 0),
            cache_write_tokens=usage.get("cache_write_tokens", 0),
        ),
        model=data.get("model", model),
        latency_ms=0,
        from_fixture=True,
        raw_text=json.dumps(data["content"]),
    )


def _save_fixture(*, feature: str, key: str, reply: ModelReply) -> None:
    path = _fixture_path(feature, key)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "model": reply.model,
                "content": reply.content,
                "usage": {
                    "input_tokens": reply.usage.input_tokens,
                    "output_tokens": reply.usage.output_tokens,
                    "cache_read_tokens": reply.usage.cache_read_tokens,
                    "cache_write_tokens": reply.usage.cache_write_tokens,
                },
            },
            indent=2,
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    logger.info("recorded fixture %s for %s", key, feature)
