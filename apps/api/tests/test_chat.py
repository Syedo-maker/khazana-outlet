"""The assistant as a conversation: threads, history, the daily cap, WhatsApp.

The model is replaced by a stub that records what it was asked. What these
tests check is everything around the model: who owns a thread, what history
goes back in, when a message is refused, and what a WhatsApp sender gets.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from commerce_helpers import auth, make_reseller
from khazana.ai.features import assistant
from khazana.ai.schemas import AssistantAnswer
from khazana.config import get_settings
from khazana.core.errors import RateLimited, SpendLimitReached
from khazana.models import AssistantMessage, WhatsAppMessage
from khazana.models.enums import ChatChannel, ChatRole, MessageDirection
from khazana.services import chat_service, whatsapp_providers, whatsapp_service
from khazana.services.whatsapp_providers import VoiceNote


@dataclass
class _Plan:
    language: str = "en"


@dataclass
class _Turn:
    answer: AssistantAnswer
    plan: _Plan = field(default_factory=_Plan)
    is_grounded: bool = True
    total_cost_usd: Decimal = Decimal("0.0042")


@dataclass
class StubAssistant:
    calls: list[dict[str, Any]] = field(default_factory=list)
    fail_with: Exception | None = None

    def __call__(self, db: Session, **kwargs: Any) -> _Turn:
        self.calls.append(kwargs)
        if self.fail_with is not None:
            raise self.fail_with
        return _Turn(
            answer=AssistantAnswer(
                answer=f"Reply {len(self.calls)}",
                language="en",
                tool_calls_made=["search_lots"],
                lot_ids_referenced=["LOT-00042"],
            )
        )


@pytest.fixture
def stub(monkeypatch: pytest.MonkeyPatch) -> StubAssistant:
    fake = StubAssistant()
    monkeypatch.setattr(assistant, "ask", fake)
    return fake


@pytest.fixture
def small_cap(monkeypatch: pytest.MonkeyPatch) -> int:
    monkeypatch.setattr(get_settings(), "assistant_daily_message_limit", 2)
    return 2


class TestConversations:
    def test_a_first_message_starts_a_thread_and_stores_both_sides(
        self, db: Session, stub: StubAssistant
    ) -> None:
        buyer = make_reseller(db)
        exchange = chat_service.send(db, user_id=buyer.id, text="Lawn kurtis in Lahore?")
        db.commit()

        assert exchange.conversation.title == "Lawn kurtis in Lahore?"
        roles = [m.role for m in exchange.conversation.messages]
        assert roles == [ChatRole.BUYER, ChatRole.ASSISTANT]
        assert exchange.reply.tools_used == {"tools": ["search_lots"], "lots": ["LOT-00042"]}
        assert exchange.reply.cost_usd == Decimal("0.0042")
        assert stub.calls[0]["history"] == ""

    def test_a_follow_up_sends_the_earlier_messages_back(
        self, db: Session, stub: StubAssistant
    ) -> None:
        buyer = make_reseller(db)
        first = chat_service.send(db, user_id=buyer.id, text="Lawn kurtis in Lahore?")
        chat_service.send(
            db, user_id=buyer.id, text="And in Karachi?", conversation_id=first.conversation.id
        )
        assert stub.calls[1]["history"] == "Buyer: Lawn kurtis in Lahore?\nAssistant: Reply 1"

    def test_history_keeps_only_the_most_recent_messages(
        self, db: Session, stub: StubAssistant, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(get_settings(), "assistant_history_messages", 2)
        buyer = make_reseller(db)
        first = chat_service.send(db, user_id=buyer.id, text="one")
        chat_service.send(db, user_id=buyer.id, text="two", conversation_id=first.conversation.id)
        chat_service.send(db, user_id=buyer.id, text="three", conversation_id=first.conversation.id)
        assert stub.calls[2]["history"] == "Buyer: two\nAssistant: Reply 2"

    def test_another_users_thread_is_not_found(self, db: Session, stub: StubAssistant) -> None:
        owner = make_reseller(db)
        other = make_reseller(db, phone="03008888888")
        thread = chat_service.send(db, user_id=owner.id, text="hello").conversation
        with pytest.raises(chat_service.NotFound):
            chat_service.send(db, user_id=other.id, text="hi", conversation_id=thread.id)
        with pytest.raises(chat_service.NotFound):
            chat_service.get_conversation(db, other.id, thread.id)
        assert len(stub.calls) == 1

    def test_a_failed_model_call_stores_nothing(self, db: Session, stub: StubAssistant) -> None:
        buyer = make_reseller(db)
        stub.fail_with = SpendLimitReached("cap")
        with pytest.raises(SpendLimitReached):
            chat_service.send(db, user_id=buyer.id, text="hello")
        assert db.scalar(select(AssistantMessage.id)) is None
        assert chat_service.messages_sent_today(db, buyer.id) == 0


class TestDailyCap:
    def test_the_cap_refuses_before_any_model_call(
        self, db: Session, stub: StubAssistant, small_cap: int
    ) -> None:
        buyer = make_reseller(db)
        for text in ("one", "two"):
            chat_service.send(db, user_id=buyer.id, text=text)
        with pytest.raises(RateLimited, match="midnight Pakistan time"):
            chat_service.send(db, user_id=buyer.id, text="three")
        assert len(stub.calls) == small_cap

    def test_the_cap_is_per_account(self, db: Session, stub: StubAssistant, small_cap: int) -> None:
        first = make_reseller(db)
        second = make_reseller(db, phone="03008888888")
        for text in ("one", "two"):
            chat_service.send(db, user_id=first.id, text=text)
        chat_service.send(db, user_id=second.id, text="mine")

    def test_the_day_turns_at_pakistan_midnight(self) -> None:
        # 20:30 UTC is 01:30 the next morning in Pakistan.
        late = datetime(2026, 11, 20, 20, 30, tzinfo=UTC)
        assert chat_service.start_of_pakistan_day(late) == datetime(2026, 11, 20, 19, 0, tzinfo=UTC)
        early = datetime(2026, 11, 20, 18, 59, tzinfo=UTC)
        assert chat_service.start_of_pakistan_day(early) == datetime(
            2026, 11, 19, 19, 0, tzinfo=UTC
        )

    def test_yesterdays_messages_do_not_count(
        self, db: Session, stub: StubAssistant, small_cap: int
    ) -> None:
        buyer = make_reseller(db)
        for text in ("one", "two"):
            chat_service.send(db, user_id=buyer.id, text=text)
        yesterday = datetime.now(UTC) - timedelta(days=1, hours=1)
        for message in db.scalars(select(AssistantMessage)):
            message.created_at = yesterday
        db.flush()
        assert chat_service.messages_sent_today(db, buyer.id) == 0


class TestEndpoints:
    def test_send_list_and_read_back(
        self, client: TestClient, db: Session, stub: StubAssistant
    ) -> None:
        buyer = make_reseller(db)
        db.commit()
        sent = client.post(
            "/assistant/messages", json={"message": "Lawn in Lahore?"}, headers=auth(buyer)
        )
        assert sent.status_code == 200, sent.text
        body = sent.json()
        assert body["reply"]["body"] == "Reply 1"
        assert body["reply"]["lot_codes"] == ["LOT-00042"]
        assert body["usage"]["used"] == 1

        listed = client.get("/assistant/conversations", headers=auth(buyer)).json()
        assert [c["id"] for c in listed] == [body["conversation"]["id"]]

        detail = client.get(
            f"/assistant/conversations/{body['conversation']['id']}", headers=auth(buyer)
        ).json()
        assert [m["role"] for m in detail["messages"]] == ["buyer", "assistant"]

    def test_another_buyer_gets_a_404(
        self, client: TestClient, db: Session, stub: StubAssistant
    ) -> None:
        owner = make_reseller(db)
        other = make_reseller(db, phone="03008888888")
        db.commit()
        thread = client.post(
            "/assistant/messages", json={"message": "hi"}, headers=auth(owner)
        ).json()["conversation"]["id"]
        response = client.get(f"/assistant/conversations/{thread}", headers=auth(other))
        assert response.status_code == 404
        assert client.get("/assistant/conversations", headers=auth(other)).json() == []

    def test_the_cap_answers_429(
        self, client: TestClient, db: Session, stub: StubAssistant, small_cap: int
    ) -> None:
        buyer = make_reseller(db)
        db.commit()
        for _ in range(small_cap):
            client.post("/assistant/messages", json={"message": "hi"}, headers=auth(buyer))
        refused = client.post("/assistant/messages", json={"message": "hi"}, headers=auth(buyer))
        assert refused.status_code == 429
        assert client.get("/assistant/usage", headers=auth(buyer)).json()["remaining"] == 0

    def test_an_anonymous_caller_is_refused(self, client: TestClient) -> None:
        assert client.post("/assistant/messages", json={"message": "hi"}).status_code == 401


class TestWhatsApp:
    def _inbound(self, db: Session, **kwargs: Any) -> whatsapp_service.InboundResult:
        sandbox = whatsapp_providers.sandbox()
        body, signature = sandbox.build_inbound(**kwargs)
        return whatsapp_service.ingest(db, "sandbox", body, signature)

    def test_a_registered_buyer_is_answered_in_a_whatsapp_thread(
        self, db: Session, stub: StubAssistant
    ) -> None:
        buyer = make_reseller(db, city="Multan")
        result = self._inbound(db, phone="+923007777777", text="Lawn kurtis?")
        assert result.status == "answered"
        assert result.reply == "Reply 1"
        assert stub.calls[0]["buyer_city"] == "Multan"
        thread = chat_service.latest_conversation(db, buyer.id, ChatChannel.WHATSAPP)
        assert thread is not None

        self._inbound(db, phone="03007777777", text="And in Karachi?")
        assert stub.calls[1]["history"].startswith("Buyer: Lawn kurtis?")
        sent = db.scalars(
            select(WhatsAppMessage).where(WhatsAppMessage.direction == MessageDirection.OUTBOUND)
        ).all()
        assert [m.body for m in sent] == ["Reply 1", "Reply 2"]

    def test_a_quiet_spell_starts_a_new_thread(self, db: Session, stub: StubAssistant) -> None:
        buyer = make_reseller(db)
        self._inbound(db, phone="03007777777", text="Lawn kurtis?")
        thread = chat_service.latest_conversation(db, buyer.id, ChatChannel.WHATSAPP)
        assert thread is not None
        thread.last_message_at = datetime.now(UTC) - timedelta(days=2)
        db.flush()
        self._inbound(db, phone="03007777777", text="Any denim?")
        assert stub.calls[1]["history"] == ""

    def test_an_unknown_number_gets_the_sign_up_reply_and_costs_nothing(
        self, db: Session, stub: StubAssistant
    ) -> None:
        result = self._inbound(db, phone="03001112222", text="Price?")
        assert result.status == "unknown_sender"
        assert result.reply is not None and "Sign up" in result.reply
        assert stub.calls == []

    def test_a_repeated_delivery_is_answered_once(self, db: Session, stub: StubAssistant) -> None:
        make_reseller(db)
        sandbox = whatsapp_providers.sandbox()
        body, signature = sandbox.build_inbound(phone="03007777777", text="hi", message_id="m1")
        whatsapp_service.ingest(db, "sandbox", body, signature)
        again = whatsapp_service.ingest(db, "sandbox", body, signature)
        assert again.duplicate
        assert len(stub.calls) == 1

    def test_a_bad_signature_is_refused(self, client: TestClient, stub: StubAssistant) -> None:
        body, _ = whatsapp_providers.sandbox().build_inbound(phone="03007777777", text="hi")
        response = client.post(
            "/whatsapp/webhooks/sandbox",
            content=body,
            headers={"X-Sandbox-Signature": "0" * 64},
        )
        assert response.status_code == 401
        assert stub.calls == []

    def test_the_signed_webhook_is_accepted(
        self, client: TestClient, db: Session, stub: StubAssistant
    ) -> None:
        make_reseller(db)
        db.commit()
        body, signature = whatsapp_providers.sandbox().build_inbound(phone="03007777777", text="hi")
        response = client.post(
            "/whatsapp/webhooks/sandbox", content=body, headers={"X-Sandbox-Signature": signature}
        )
        assert response.status_code == 200, response.text
        assert response.json() == {"status": "answered", "duplicate": False}

    def test_the_cap_reaches_whatsapp_as_a_reply(
        self, db: Session, stub: StubAssistant, small_cap: int
    ) -> None:
        make_reseller(db)
        for text in ("one", "two"):
            self._inbound(db, phone="03007777777", text=text)
        result = self._inbound(db, phone="03007777777", text="three")
        assert result.status == "rate_limited"
        assert len(stub.calls) == small_cap

    def test_an_unavailable_assistant_gets_a_fixed_reply(
        self, db: Session, stub: StubAssistant
    ) -> None:
        make_reseller(db)
        stub.fail_with = SpendLimitReached("cap")
        result = self._inbound(db, phone="03007777777", text="hi")
        assert result.status == "assistant_unavailable"
        assert result.reply == whatsapp_service.UNAVAILABLE_REPLY


class TestVoiceNotes:
    def _voice(
        self,
        db: Session,
        transcript: str | None,
        confidence: float | None,
        language: str | None = "ur",
    ) -> Any:
        sandbox = whatsapp_providers.sandbox()
        body, signature = sandbox.build_inbound(
            phone="03007777777",
            voice=VoiceNote(
                media_id="media-1",
                duration_seconds=6,
                sandbox_transcript=transcript,
                sandbox_confidence=confidence,
                sandbox_language=language,
            ),
        )
        return whatsapp_service.ingest(db, "sandbox", body, signature)

    def test_a_clear_voice_note_is_answered_from_its_transcript(
        self, db: Session, stub: StubAssistant
    ) -> None:
        make_reseller(db)
        result = self._voice(db, "Lahore mein lawn ke suit hain?", 0.91)
        assert result.status == "answered"
        assert stub.calls[0]["message"] == "Lahore mein lawn ke suit hain?"
        logged = db.scalar(
            select(WhatsAppMessage).where(WhatsAppMessage.direction == MessageDirection.INBOUND)
        )
        assert logged is not None
        assert logged.transcript_confidence == pytest.approx(0.91)
        assert logged.media_key == "media-1"
        assert logged.transcript_language == "ur"

    @pytest.mark.parametrize("language", ["pa", "sd", "ps"])
    def test_punjabi_sindhi_and_pashto_voice_notes_are_answered(
        self, db: Session, stub: StubAssistant, language: str
    ) -> None:
        make_reseller(db)
        result = self._voice(db, "Lawn de suit kinne de ne?", 0.8, language)
        assert result.status == "answered"
        logged = db.scalar(
            select(WhatsAppMessage).where(WhatsAppMessage.direction == MessageDirection.INBOUND)
        )
        assert logged is not None and logged.transcript_language == language

    def test_an_unknown_language_code_is_not_stored(self, db: Session, stub: StubAssistant) -> None:
        make_reseller(db)
        self._voice(db, "hello", 0.9, "xx")
        logged = db.scalar(
            select(WhatsAppMessage).where(WhatsAppMessage.direction == MessageDirection.INBOUND)
        )
        assert logged is not None and logged.transcript_language is None

    @pytest.mark.parametrize(("transcript", "confidence"), [("kuch", 0.3), (None, None)])
    def test_an_unclear_voice_note_asks_the_buyer_to_type(
        self, db: Session, stub: StubAssistant, transcript: str | None, confidence: float | None
    ) -> None:
        make_reseller(db)
        result = self._voice(db, transcript, confidence)
        assert result.status == "voice_unclear"
        assert result.reply == whatsapp_service.VOICE_UNCLEAR_REPLY
        assert stub.calls == []

    def test_the_admin_sandbox_sends_a_voice_note(
        self, client: TestClient, db: Session, stub: StubAssistant, admin_user: Any
    ) -> None:
        make_reseller(db)
        db.commit()
        response = client.post(
            "/admin/whatsapp/sandbox/inbound",
            json={"phone": "03007777777", "voice_transcript": "denim?", "voice_confidence": 0.2},
            headers=auth(admin_user),
        )
        assert response.status_code == 200, response.text
        assert response.json()["status"] == "voice_unclear"
        log = client.get("/admin/whatsapp/messages", headers=auth(admin_user)).json()
        assert {row["direction"] for row in log} == {"inbound", "outbound"}
