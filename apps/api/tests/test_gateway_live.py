"""What the gateway actually sends to the API, with a fake client.

Every other gateway test runs offline from fixtures, so until week 53 nothing
checked the live request itself: which endpoint, which model settings, where
the cache breakpoint sits, and what happens on a refusal or a fallback.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import anthropic
import pytest

from khazana.ai.gateway import client as gateway_client
from khazana.ai.gateway.client import FALLBACK_BETA, AiClientError, call_model
from khazana.ai.gateway.cost import price_call
from khazana.ai.gateway.models import HAIKU_4_5, HAIKU_5_5, OPUS_4_8, OPUS_5_5
from khazana.config import get_settings


def _response(model: str, *, stop: str = "end_turn", cache_read: int = 600) -> SimpleNamespace:
    return SimpleNamespace(
        model=model,
        stop_reason=stop,
        content=[SimpleNamespace(type="text", text='{"ok": true}')],
        usage=SimpleNamespace(
            input_tokens=100,
            output_tokens=20,
            cache_read_input_tokens=cache_read,
            cache_creation_input_tokens=0,
        ),
    )


class _Fake:
    """Records every request; answers with whatever ``reply`` returns."""

    def __init__(self, reply: Any) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []
        fake = self

        class _Messages:
            def create(self, **kwargs: Any) -> Any:
                fake.calls.append(("messages", kwargs))
                return reply(kwargs)

        class _BetaMessages:
            def create(self, **kwargs: Any) -> Any:
                fake.calls.append(("beta", kwargs))
                return reply(kwargs)

        self.messages = _Messages()
        self.beta = SimpleNamespace(messages=_BetaMessages())


@pytest.fixture
def live(monkeypatch: pytest.MonkeyPatch):  # type: ignore[no-untyped-def]
    monkeypatch.setattr(get_settings(), "ai_offline", False)
    monkeypatch.setattr(get_settings(), "anthropic_api_key", "sk-test-not-real")

    def install(reply: Any) -> _Fake:
        fake = _Fake(reply)
        monkeypatch.setattr(anthropic, "Anthropic", lambda **_: fake)
        return fake

    return install


def _call(model: str, **overrides: Any) -> Any:
    return call_model(
        model=model,
        system="You price surplus stock." * 10,
        user_text="Lot: 100 kurtas",
        output_schema={"type": "object", "properties": {}, "additionalProperties": False},
        effort=overrides.pop("effort", "low"),
        max_tokens=overrides.pop("max_tokens", 1_000),
        feature="pricing",
        **overrides,
    )


def test_an_opus_call_carries_the_refusal_fallback_and_the_cache_breakpoint(live) -> None:  # type: ignore[no-untyped-def]
    fake = live(lambda kwargs: _response(kwargs["model"]))
    reply = _call(OPUS_5_5)
    endpoint, request = fake.calls[0]
    assert endpoint == "beta"
    assert request["betas"] == [FALLBACK_BETA]
    assert request["fallbacks"] == [{"model": OPUS_4_8}]
    assert request["system"][-1]["cache_control"] == {"type": "ephemeral"}
    assert request["output_config"]["effort"] == "low"
    assert "thinking" not in request, "Opus 5.5 rejects a thinking setting"
    assert reply.model == OPUS_5_5


def test_haiku_5_5_uses_the_plain_endpoint_without_a_token_budget(live) -> None:  # type: ignore[no-untyped-def]
    fake = live(lambda kwargs: _response(kwargs["model"]))
    _call(HAIKU_5_5, max_tokens=4_000)
    endpoint, request = fake.calls[0]
    assert endpoint == "messages"
    assert "fallbacks" not in request
    assert "thinking" not in request, "budget_tokens is a 400 on Haiku 5.5"


def test_haiku_4_5_keeps_its_older_thinking_form(live) -> None:  # type: ignore[no-untyped-def]
    fake = live(lambda kwargs: _response(kwargs["model"]))
    _call(HAIKU_4_5, max_tokens=4_000, effort=None)
    assert fake.calls[0][1]["thinking"] == {"type": "enabled", "budget_tokens": 1_024}


def test_a_reply_served_by_the_fallback_is_priced_as_the_fallback(live) -> None:  # type: ignore[no-untyped-def]
    live(lambda kwargs: _response(OPUS_4_8))
    reply = _call(OPUS_5_5)
    assert reply.model == OPUS_4_8
    assert price_call(reply.model, reply.usage) > price_call(OPUS_5_5, reply.usage)


def test_a_refusal_from_the_whole_chain_is_a_clear_error(live) -> None:  # type: ignore[no-untyped-def]
    live(lambda kwargs: _response(kwargs["model"], stop="refusal"))
    with pytest.raises(AiClientError, match="declined"):
        _call(OPUS_5_5)


def test_a_cache_that_never_engages_is_reported(live, caplog) -> None:  # type: ignore[no-untyped-def]
    live(lambda kwargs: _response(kwargs["model"], cache_read=0))
    with caplog.at_level("WARNING", logger=gateway_client.__name__):
        _call(HAIKU_5_5)
    assert "prompt cache did not engage" in caplog.text
