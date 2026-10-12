"""The buyer assistant and the tools that keep it honest.

Most of this file is about the tools, deliberately. The tools are where the
anti hallucination guarantee actually lives: the model can only state what a
lookup returned, so a tool that leaks a private lot or another buyer's order
defeats every prompt rule above it.
"""

from __future__ import annotations

import json

import pytest
from sqlalchemy.orm import Session

from khazana.ai.features import assistant
from khazana.ai.gateway import client, prompts
from khazana.ai.schemas import PlannedToolCall, ToolPlan
from khazana.ai.tools import catalog_tools as tools
from khazana.core.errors import ValidationFailed
from khazana.models import Brand, Category, Lot, ManifestLine, Order, User
from khazana.models.base import utcnow
from khazana.models.enums import (
    ConditionGrade,
    LotStatus,
    OrderStatus,
    UserRole,
    Visibility,
)


@pytest.fixture
def category(db: Session) -> Category:
    row = Category(name="Womenswear stitched", slug="womenswear-stitched")
    db.add(row)
    db.commit()
    return row


def make_lot(
    db: Session,
    brand: Brand,
    category: Category,
    *,
    code: str,
    title: str = "Printed lawn kurtis",
    status: LotStatus = LotStatus.LIVE,
    visibility: Visibility = Visibility.PUBLIC,
    approved: bool = True,
    city: str = "Lahore",
    pieces: int = 100,
    minimum: int = 50,
    lot_price: int = 50_000,
) -> Lot:
    lot = Lot(
        lot_code=code,
        brand_id=brand.id,
        category_id=category.id,
        title=title,
        description=title,
        condition_grade=ConditionGrade.A,
        total_pieces=pieces,
        retail_price_per_piece_pkr=2_000,
        lot_price_pkr=lot_price,
        min_order_pieces=minimum,
        stock_city=city,
        status=status,
        visibility=visibility,
        approved_at=utcnow() if approved else None,
    )
    db.add(lot)
    db.flush()
    db.add(
        ManifestLine(
            lot_id=lot.id, brand_id=brand.id, size="M", color="black", pieces=pieces
        )
    )
    db.commit()
    return lot


# ------------------------------------------------------------------- tools


class TestVisibility:
    def test_a_draft_lot_is_invisible_to_every_tool(
        self, db: Session, two_brands, category
    ) -> None:  # type: ignore[no-untyped-def]
        """The guarantee lives here, not in the prompt.

        If a tool hands the assistant an unapproved listing, no instruction
        above it can put that back.
        """
        (brand, _), _ = two_brands
        make_lot(db, brand, category, code="LOT-DRAFT", status=LotStatus.DRAFT, approved=False)

        assert tools.search_lots(db, query="lawn")["found"] == 0
        assert tools.get_lot(db, lot_code="LOT-DRAFT")["found"] is False
        assert tools.check_availability(db, lot_code="LOT-DRAFT", pieces=50)["available"] is False

    def test_a_private_lot_is_invisible_to_the_assistant(
        self, db: Session, two_brands, category
    ) -> None:  # type: ignore[no-untyped-def]
        (brand, _), _ = two_brands
        make_lot(db, brand, category, code="LOT-PRIV", visibility=Visibility.PRIVATE)
        assert tools.search_lots(db, query="lawn")["found"] == 0

    def test_a_soft_deleted_lot_is_invisible(self, db: Session, two_brands, category) -> None:  # type: ignore[no-untyped-def]
        (brand, _), _ = two_brands
        lot = make_lot(db, brand, category, code="LOT-DEL")
        lot.deleted_at = utcnow()
        db.commit()
        assert tools.search_lots(db, query="lawn")["found"] == 0

    def test_an_unbranded_lot_never_reveals_the_real_brand_name(
        self, db: Session, two_brands, category
    ) -> None:  # type: ignore[no-untyped-def]
        """The assistant cannot leak what it was never given."""
        (brand, _), _ = two_brands
        brand.unbranded_label = "leading Pakistani lawn brand"
        db.commit()
        make_lot(db, brand, category, code="LOT-UNB", visibility=Visibility.UNBRANDED)

        result = tools.get_lot(db, lot_code="LOT-UNB")

        assert result["brand"] == "leading Pakistani lawn brand"
        assert brand.name not in json.dumps(result)


class TestSearchLots:
    def test_filters_are_honoured_exactly(self, db: Session, two_brands, category) -> None:  # type: ignore[no-untyped-def]
        (brand, _), _ = two_brands
        make_lot(db, brand, category, code="LOT-LHR", city="Lahore")
        make_lot(db, brand, category, code="LOT-KHI", city="Karachi")

        found = tools.search_lots(db, city="Karachi")

        assert found["found"] == 1
        assert found["lots"][0]["lot_code"] == "LOT-KHI"

    def test_a_price_ceiling_excludes_dearer_lots(
        self, db: Session, two_brands, category
    ) -> None:  # type: ignore[no-untyped-def]
        (brand, _), _ = two_brands
        make_lot(db, brand, category, code="LOT-CHEAP", pieces=100, lot_price=20_000)
        make_lot(db, brand, category, code="LOT-DEAR", pieces=100, lot_price=90_000)

        found = tools.search_lots(db, max_price_per_piece_pkr=300)

        assert [lot["lot_code"] for lot in found["lots"]] == ["LOT-CHEAP"]

    def test_an_unknown_category_says_so_instead_of_returning_everything(
        self, db: Session, two_brands, category
    ) -> None:  # type: ignore[no-untyped-def]
        """Silently ignoring a filter is how a wrong answer looks right."""
        (brand, _), _ = two_brands
        make_lot(db, brand, category, code="LOT-1")

        found = tools.search_lots(db, category="aerospace-parts")

        assert found["found"] == 0
        assert "No category" in found["note"]


class TestAvailability:
    def test_below_the_minimum_order_is_refused_with_the_number(
        self, db: Session, two_brands, category
    ) -> None:  # type: ignore[no-untyped-def]
        """The first thing that makes a deal impossible, so it is explicit."""
        (brand, _), _ = two_brands
        make_lot(db, brand, category, code="LOT-1", minimum=50)

        result = tools.check_availability(db, lot_code="LOT-1", pieces=10)

        assert result["available"] is False
        assert result["minimum_order_pieces"] == 50

    def test_more_than_the_lot_holds_is_refused(
        self, db: Session, two_brands, category
    ) -> None:  # type: ignore[no-untyped-def]
        (brand, _), _ = two_brands
        make_lot(db, brand, category, code="LOT-1", pieces=100)

        result = tools.check_availability(db, lot_code="LOT-1", pieces=500)

        assert result["available"] is False
        assert result["total_pieces"] == 100

    def test_a_valid_quantity_returns_the_arithmetic(
        self, db: Session, two_brands, category
    ) -> None:  # type: ignore[no-untyped-def]
        (brand, _), _ = two_brands
        make_lot(db, brand, category, code="LOT-1", pieces=100, lot_price=50_000, minimum=50)

        result = tools.check_availability(db, lot_code="LOT-1", pieces=60)

        assert result["available"] is True
        assert result["price_per_piece_pkr"] == 500
        assert result["subtotal_pkr"] == 30_000


class TestOrderPrivacy:
    def _order(self, db: Session, brand: Brand, lot: Lot, buyer: User, code: str) -> Order:
        order = Order(
            order_code=code,
            lot_id=lot.id,
            brand_id=brand.id,
            buyer_user_id=buyer.id,
            pieces=50,
            unit_price_pkr=500,
            subtotal_pkr=25_000,
            shipping_pkr=0,
            total_pkr=25_000,
            commission_percent=15,
            commission_pkr=3_750,
            brand_payout_pkr=21_250,
            status=OrderStatus.SHIPPED,
            delivery_city="Multan",
            delivery_address="Shop 14, Multan",
            delivery_phone="03001234567",
        )
        db.add(order)
        db.commit()
        return order

    def test_a_buyer_sees_their_own_order(self, db: Session, two_brands, category) -> None:  # type: ignore[no-untyped-def]
        (brand, owner), _ = two_brands
        lot = make_lot(db, brand, category, code="LOT-1")
        self._order(db, brand, lot, owner, "ORD-MINE")

        result = tools.get_order_status(db, order_code="ORD-MINE", buyer_user_id=owner.id)

        assert result["found"] is True
        assert result["status"] == "shipped"

    def test_a_stranger_cannot_read_someone_elses_order(
        self, db: Session, two_brands, category
    ) -> None:  # type: ignore[no-untyped-def]
        """Order codes are guessable, and the assistant is a public surface.

        The buyer identifier comes from the authenticated session and is never
        taken from the conversation, so guessing a code reveals nothing.
        """
        (brand, owner), _ = two_brands
        lot = make_lot(db, brand, category, code="LOT-1")
        self._order(db, brand, lot, owner, "ORD-00001")

        stranger = User(phone="03008888888", full_name="Nosy", role=UserRole.RESELLER)
        db.add(stranger)
        db.commit()

        result = tools.get_order_status(db, order_code="ORD-00001", buyer_user_id=stranger.id)

        assert result["found"] is False
        assert "Multan" not in json.dumps(result)

    def test_the_dispatcher_refuses_a_buyer_id_from_the_model(
        self, db: Session, two_brands, category
    ) -> None:  # type: ignore[no-untyped-def]
        """A planned call cannot smuggle in a different buyer."""
        (brand, owner), _ = two_brands
        lot = make_lot(db, brand, category, code="LOT-1")
        self._order(db, brand, lot, owner, "ORD-MINE")

        stranger = User(phone="03007777777", full_name="Nosy", role=UserRole.RESELLER)
        db.add(stranger)
        db.commit()

        result = tools.run_tool(
            db,
            "get_order_status",
            {"order_code": "ORD-MINE", "buyer_user_id": owner.id},
            buyer_user_id=stranger.id,
        )

        assert result["found"] is False


class TestDeliveryAndDrafts:
    def test_delivery_is_labelled_an_estimate(self, db: Session, two_brands, category) -> None:  # type: ignore[no-untyped-def]
        (brand, _), _ = two_brands
        make_lot(db, brand, category, code="LOT-1", city="Lahore")

        result = tools.estimate_delivery(db, lot_code="LOT-1", to_city="Karachi")

        assert result["is_estimate"] is True
        assert result["working_days_low"] <= result["working_days_high"]

    def test_a_remote_city_takes_longer_than_a_major_one(
        self, db: Session, two_brands, category
    ) -> None:  # type: ignore[no-untyped-def]
        (brand, _), _ = two_brands
        make_lot(db, brand, category, code="LOT-1", city="Lahore")

        major = tools.estimate_delivery(db, lot_code="LOT-1", to_city="Karachi")
        remote = tools.estimate_delivery(db, lot_code="LOT-1", to_city="Gwadar")

        assert remote["working_days_high"] > major["working_days_high"]

    def test_a_draft_reserves_nothing_and_says_so(
        self, db: Session, two_brands, category
    ) -> None:  # type: ignore[no-untyped-def]
        """An assistant that could place a binding order can be talked into it."""
        (brand, owner), _ = two_brands
        make_lot(db, brand, category, code="LOT-1", pieces=100, minimum=50, lot_price=50_000)

        draft = tools.create_order_draft(
            db, lot_code="LOT-1", pieces=60, buyer_user_id=owner.id, city="Multan"
        )

        assert draft["created"] is True
        assert draft["is_draft"] is True
        assert draft["requires_confirmation"] is True
        assert draft["subtotal_pkr"] == 30_000

        from khazana.models import Order as OrderModel

        assert db.query(OrderModel).count() == 0, "a draft must not create an order"

    def test_a_draft_below_the_minimum_is_refused(
        self, db: Session, two_brands, category
    ) -> None:  # type: ignore[no-untyped-def]
        (brand, owner), _ = two_brands
        make_lot(db, brand, category, code="LOT-1", minimum=50)

        draft = tools.create_order_draft(
            db, lot_code="LOT-1", pieces=5, buyer_user_id=owner.id, city="Multan"
        )

        assert draft["created"] is False


# --------------------------------------------------------------- the turn


class TestExecutePlan:
    def test_an_unknown_tool_is_dropped_rather_than_crashing(
        self, db: Session, two_brands
    ) -> None:  # type: ignore[no-untyped-def]
        """A plan is a model output, so it is validated and not trusted."""
        (_brand, owner), _ = two_brands
        plan = ToolPlan(
            calls=[PlannedToolCall(tool="delete_everything", arguments={})],
            language="en",
        )

        results, executed, rejected = assistant.execute_plan(db, plan, buyer_user_id=owner.id)

        assert results == {}
        assert executed == []
        assert rejected == ["delete_everything"]

    def test_bad_arguments_become_an_error_entry_not_a_lost_turn(
        self, db: Session, two_brands
    ) -> None:  # type: ignore[no-untyped-def]
        (_brand, owner), _ = two_brands
        plan = ToolPlan(
            calls=[PlannedToolCall(tool="get_lot", arguments={"wrong_arg": "x"})],
            language="en",
        )

        results, executed, rejected = assistant.execute_plan(db, plan, buyer_user_id=owner.id)

        assert executed == []
        assert rejected == ["get_lot"]
        assert "error" in next(iter(results.values()))

    def test_the_call_count_is_capped(self, db: Session, two_brands, category) -> None:  # type: ignore[no-untyped-def]
        (brand, owner), _ = two_brands
        make_lot(db, brand, category, code="LOT-1")
        plan = ToolPlan(
            calls=[PlannedToolCall(tool="search_lots", arguments={}) for _ in range(6)],
            language="en",
        )

        _results, executed, _rejected = assistant.execute_plan(db, plan, buyer_user_id=owner.id)

        assert len(executed) <= assistant.MAX_TOOL_CALLS

    def test_needs_no_tools_runs_nothing(self, db: Session, two_brands) -> None:  # type: ignore[no-untyped-def]
        (_brand, owner), _ = two_brands
        plan = ToolPlan(calls=[], needs_no_tools=True, language="en")

        results, executed, _rejected = assistant.execute_plan(db, plan, buyer_user_id=owner.id)

        assert results == {}
        assert executed == []


class TestRenderResults:
    def test_an_empty_block_instructs_rather_than_being_blank(self) -> None:
        """A blank section reads to a model like a gap to fill in."""
        rendered = assistant.render_results({})
        assert "No lookups were run" in rendered
        assert "must say so" in rendered

    def test_a_long_result_is_truncated(self) -> None:
        """A tool result is paid for per token, so the block is capped."""
        huge = {"search_lots#1": {"lots": [{"title": "x" * 200} for _ in range(200)]}}
        rendered = assistant.render_results(huge)
        assert len(rendered) < assistant.MAX_TOOL_RESULT_CHARS + 200
        assert "truncated" in rendered


class TestFullTurn:
    def _stub(self, tmp_path, monkeypatch, prompt_name: str, values: dict, content: dict) -> None:  # type: ignore[no-untyped-def]
        monkeypatch.setattr(client, "FIXTURE_DIR", tmp_path)
        prompt = prompts.load(prompt_name)
        key = client.fixture_key(
            feature="assistant_buyer",
            prompt_name=prompt.name,
            prompt_version=prompt.version,
            user_text=prompt.render(**values),
            images=0,
        )
        path = tmp_path / "assistant_buyer" / f"{key}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(
                {
                    "model": "claude-opus-5-5",
                    "content": content,
                    "usage": {"input_tokens": 1500, "output_tokens": 200},
                }
            ),
            encoding="utf-8",
        )

    def test_a_roman_urdu_question_is_answered_from_a_lookup(
        self, db: Session, two_brands, category, tmp_path, monkeypatch
    ) -> None:  # type: ignore[no-untyped-def]
        (brand, owner), _ = two_brands
        make_lot(db, brand, category, code="LOT-1", city="Lahore", minimum=50)

        message = "Lahore mein kurtis hain? kitne ka hai?"
        self._stub(
            tmp_path,
            monkeypatch,
            assistant.PLAN_PROMPT,
            {"message": message, "buyer_city": "Multan"},
            {
                "calls": [
                    {"tool": "search_lots", "arguments": {"query": "kurtis", "city": "Lahore"}}
                ],
                "needs_no_tools": False,
                "language": "ur_roman",
            },
        )

        plan = ToolPlan(
            calls=[
                PlannedToolCall(tool="search_lots", arguments={"query": "kurtis", "city": "Lahore"})
            ],
            language="ur_roman",
        )
        results, _executed, _rejected = assistant.execute_plan(db, plan, buyer_user_id=owner.id)

        self._stub(
            tmp_path,
            monkeypatch,
            assistant.ANSWER_PROMPT,
            {
                "message": message,
                "buyer_city": "Multan",
                "today": tools.now_iso(),
                "tool_results": assistant.render_results(results),
            },
            {
                "answer": "LOT-1 available hai, 500 rupay per piece, minimum 50 pieces.",
                "language": "ur_roman",
                "tool_calls_made": ["search_lots"],
                "lot_ids_referenced": ["LOT-1"],
                "declined": False,
                "decline_reason": None,
            },
        )

        turn = assistant.ask(db, message=message, buyer_user_id=owner.id, buyer_city="Multan")

        assert turn.answer.language == "ur_roman"
        assert turn.answer.tool_calls_made == ["search_lots"]
        assert turn.is_grounded
        assert turn.plan.language == "ur_roman"

    def test_the_executed_tool_record_overrides_what_the_model_claimed(
        self, db: Session, two_brands, category, tmp_path, monkeypatch
    ) -> None:  # type: ignore[no-untyped-def]
        """What actually ran is authoritative, not what the model said ran.

        Otherwise a model could assert a lookup it never made and the
        grounding check would believe it.
        """
        (_brand, owner), _ = two_brands
        message = "hello"
        self._stub(
            tmp_path,
            monkeypatch,
            assistant.PLAN_PROMPT,
            {"message": message, "buyer_city": "not given"},
            {"calls": [], "needs_no_tools": True, "language": "en"},
        )
        self._stub(
            tmp_path,
            monkeypatch,
            assistant.ANSWER_PROMPT,
            {
                "message": message,
                "buyer_city": "not given",
                "today": tools.now_iso(),
                "tool_results": assistant.render_results({}),
            },
            {
                "answer": "We have 400 kurtis at 300 rupees.",
                "language": "en",
                "tool_calls_made": ["search_lots", "get_lot"],
                "lot_ids_referenced": [],
                "declined": False,
                "decline_reason": None,
            },
        )

        turn = assistant.ask(db, message=message, buyer_user_id=owner.id)

        assert turn.answer.tool_calls_made == []
        assert not turn.is_grounded

    def test_an_empty_message_is_refused_before_any_cost(
        self, db: Session, two_brands
    ) -> None:  # type: ignore[no-untyped-def]
        (_brand, owner), _ = two_brands
        with pytest.raises(ValidationFailed):
            assistant.ask(db, message="   ", buyer_user_id=owner.id)

    def test_a_long_message_is_bounded(self) -> None:
        assert len(assistant._clean_message("x" * 9_000)) == assistant.MAX_MESSAGE_CHARS
