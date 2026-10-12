"""The tools the assistant is allowed to call.

Every one of these is a real database query. This is the whole defence against
the failure that kills a marketplace assistant: a confident, invented stock
level or price quoted to a buyer in a negotiation.

Three rules hold across the file.

1. **Read mostly.** Nothing here moves money, changes a price, approves a
   listing or alters a role. The one tool that writes, ``create_order_draft``,
   creates a draft that a human must confirm, and it reserves nothing.
2. **Visibility is applied inside the tool.** A tool that returned a private
   or unapproved lot would hand the assistant a fact it is not allowed to
   repeat, and no prompt rule can put that back.
3. **Every result is JSON serialisable and small.** A tool result goes back
   into the model's context and is paid for per token, so these return the
   fields a buyer would ask about, not whole rows.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from ...models import Brand, Category, Lot, ManifestLine, Order
from ...models.enums import LotStatus, Visibility

logger = logging.getLogger(__name__)

MAX_RESULTS = 8

# Courier transit times, in working days, between city tiers. Deliberately a
# table rather than a model guess: a delivery estimate a buyer plans around is
# an operational fact, and when the courier integration lands in Phase 3 this
# is replaced by the courier's own quote rather than by better prompting.
MAJOR_CITIES = {"Karachi", "Lahore", "Islamabad", "Rawalpindi", "Faisalabad"}


def visible_lots(statement: Any) -> Any:
    """Restrict any lot query to what a buyer is allowed to see.

    Applied inside every tool rather than trusted to the caller. A private lot
    surfaced to the assistant is a brand protection breach that no later check
    can undo.
    """
    return statement.where(
        Lot.status == LotStatus.LIVE,
        Lot.approved_at.is_not(None),
        Lot.deleted_at.is_(None),
        Lot.visibility != Visibility.PRIVATE,
    )


def brand_label(db: Session, lot: Lot) -> str:
    """What the assistant may call this lot's brand.

    An unbranded listing returns the generic label the brand chose, never the
    real name. The assistant cannot leak what it was never given.
    """
    if lot.visibility == Visibility.UNBRANDED:
        brand = db.get(Brand, lot.brand_id)
        return (brand.unbranded_label if brand else None) or "a Pakistani brand"
    brand = db.get(Brand, lot.brand_id)
    return brand.name if brand else "unknown"


def _lot_summary(db: Session, lot: Lot) -> dict[str, Any]:
    category = db.get(Category, lot.category_id)
    return {
        "lot_code": lot.lot_code,
        "title": lot.title,
        "brand": brand_label(db, lot),
        "category": category.name if category else "unknown",
        "condition_grade": lot.condition_grade.value,
        "total_pieces": lot.total_pieces,
        "price_per_piece_pkr": round(lot.price_per_piece_pkr),
        "lot_price_pkr": lot.lot_price_pkr,
        "discount_percent": round(lot.discount_percent),
        "minimum_order_pieces": lot.min_order_pieces,
        "stock_city": lot.stock_city,
    }


# --------------------------------------------------------------------- tools


def search_lots(
    db: Session,
    *,
    query: str | None = None,
    category: str | None = None,
    city: str | None = None,
    max_price_per_piece_pkr: int | None = None,
    limit: int = MAX_RESULTS,
) -> dict[str, Any]:
    """Find lots a buyer can actually order.

    Keyword and filter based. Semantic search is a separate path, because a
    buyer asking a precise filtered question wants the filter honoured exactly
    rather than approximately.
    """
    statement = visible_lots(select(Lot))

    if query:
        pattern = f"%{query.strip().lower()}%"
        statement = statement.where(
            or_(Lot.title.ilike(pattern), Lot.description.ilike(pattern))
        )

    if category:
        category_row = db.scalars(
            select(Category).where(
                or_(Category.slug == category.lower(), Category.name.ilike(f"%{category}%"))
            )
        ).first()
        if category_row is None:
            return {
                "found": 0,
                "lots": [],
                "note": f"No category matching {category!r} exists on the platform.",
            }
        statement = statement.where(Lot.category_id == category_row.id)

    if city:
        statement = statement.where(Lot.stock_city.ilike(f"%{city.strip()}%"))

    rows = db.scalars(statement.order_by(Lot.created_at.desc()).limit(min(limit, MAX_RESULTS))).all()

    lots = [_lot_summary(db, lot) for lot in rows]
    if max_price_per_piece_pkr is not None:
        lots = [lot for lot in lots if lot["price_per_piece_pkr"] <= max_price_per_piece_pkr]

    return {"found": len(lots), "lots": lots}


def get_lot(db: Session, *, lot_code: str) -> dict[str, Any]:
    """Full detail for one lot, including its size and colour breakdown."""
    lot = db.scalars(visible_lots(select(Lot)).where(Lot.lot_code == lot_code.strip())).first()
    if lot is None:
        return {
            "found": False,
            "note": f"No lot with code {lot_code!r} is available. It may be sold, "
            "withdrawn, or private to verified buyers.",
        }

    lines = db.scalars(select(ManifestLine).where(ManifestLine.lot_id == lot.id)).all()
    summary = _lot_summary(db, lot)
    summary["found"] = True
    summary["manifest"] = [
        {"size": line.size, "colour": line.color, "pieces": line.pieces} for line in lines
    ]
    summary["manifest_total"] = sum(line.pieces for line in lines)
    summary["description"] = (lot.description or "")[:600]
    return summary


def check_availability(db: Session, *, lot_code: str, pieces: int) -> dict[str, Any]:
    """Whether a quantity can be ordered right now.

    Returns a plain yes or no with the reason, so the assistant reports a fact
    rather than reasoning its way to an optimistic answer.
    """
    lot = db.scalars(visible_lots(select(Lot)).where(Lot.lot_code == lot_code.strip())).first()
    if lot is None:
        return {"available": False, "reason": "That lot is not available."}

    if pieces < lot.min_order_pieces:
        return {
            "available": False,
            "reason": f"The minimum order for this lot is {lot.min_order_pieces} pieces.",
            "minimum_order_pieces": lot.min_order_pieces,
        }
    if pieces > lot.total_pieces:
        return {
            "available": False,
            "reason": f"Only {lot.total_pieces} pieces are in this lot.",
            "total_pieces": lot.total_pieces,
        }

    return {
        "available": True,
        "pieces": pieces,
        "price_per_piece_pkr": round(lot.price_per_piece_pkr),
        "subtotal_pkr": round(lot.price_per_piece_pkr * pieces),
    }


def get_order_status(db: Session, *, order_code: str, buyer_user_id: str) -> dict[str, Any]:
    """One order, and only if it belongs to the person asking.

    The buyer identifier comes from the authenticated session, never from the
    conversation. Without that, anyone who guessed an order code could read a
    stranger's delivery address through the assistant.
    """
    order = db.scalars(
        select(Order).where(
            Order.order_code == order_code.strip(), Order.buyer_user_id == buyer_user_id
        )
    ).first()
    if order is None:
        return {"found": False, "note": "No order with that code belongs to this account."}

    return {
        "found": True,
        "order_code": order.order_code,
        "status": order.status.value,
        "pieces": order.pieces,
        "total_pkr": order.total_pkr,
        "delivery_city": order.delivery_city,
        "placed_on": order.created_at.date().isoformat(),
        "confirmed_on": order.confirmed_at.date().isoformat() if order.confirmed_at else None,
    }


def estimate_delivery(db: Session, *, lot_code: str, to_city: str) -> dict[str, Any]:
    """Working day range for a courier between two cities.

    A table, not a model guess, and labelled as an estimate. Phase 3 replaces
    it with the courier's own quote.
    """
    lot = db.scalars(visible_lots(select(Lot)).where(Lot.lot_code == lot_code.strip())).first()
    if lot is None:
        return {"known": False, "note": "That lot is not available."}

    origin = lot.stock_city.strip().title()
    destination = to_city.strip().title()

    if origin == destination:
        low, high = 1, 2
    elif origin in MAJOR_CITIES and destination in MAJOR_CITIES:
        low, high = 2, 3
    elif origin in MAJOR_CITIES or destination in MAJOR_CITIES:
        low, high = 3, 5
    else:
        low, high = 4, 7

    return {
        "known": True,
        "from_city": origin,
        "to_city": destination,
        "working_days_low": low,
        "working_days_high": high,
        "is_estimate": True,
        "note": "Estimate from city tiers, not a courier quote.",
    }


def create_order_draft(
    db: Session, *, lot_code: str, pieces: int, buyer_user_id: str, city: str
) -> dict[str, Any]:
    """Prepare an order for a human to confirm. Reserves nothing.

    The only tool that is not purely read only, and it still writes nothing to
    the database. It returns a priced draft that the buyer confirms in the
    interface, where the real order is created. An assistant that could place
    a binding order is an assistant that can be talked into placing one.
    """
    availability = check_availability(db, lot_code=lot_code, pieces=pieces)
    if not availability.get("available"):
        return {"created": False, "reason": availability.get("reason")}

    delivery = estimate_delivery(db, lot_code=lot_code, to_city=city)

    return {
        "created": True,
        "is_draft": True,
        "requires_confirmation": True,
        "lot_code": lot_code,
        "pieces": pieces,
        "subtotal_pkr": availability["subtotal_pkr"],
        "delivery_city": city,
        "estimated_working_days": [
            delivery.get("working_days_low"),
            delivery.get("working_days_high"),
        ],
        "note": "Nothing is reserved or charged. The buyer must confirm this in the app.",
    }


# ----------------------------------------------------------------- registry

#: Tool schemas as the API expects them. ``strict`` keeps the arguments schema
#: valid, which matters because forced tool choice is not available on the
#: current models and the prompt does the steering instead.
TOOL_SCHEMAS: list[dict[str, Any]] = [
    {
        "name": "search_lots",
        "description": (
            "Search available stock lots by keywords, category, city and maximum "
            "price per piece. Returns only lots a buyer can order right now."
        ),
        "strict": True,
        "input_schema": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "query": {"type": ["string", "null"], "description": "Free text keywords"},
                "category": {"type": ["string", "null"]},
                "city": {"type": ["string", "null"]},
                "max_price_per_piece_pkr": {"type": ["integer", "null"]},
            },
            "required": ["query", "category", "city", "max_price_per_piece_pkr"],
        },
    },
    {
        "name": "get_lot",
        "description": "Full detail for one lot by its code, including the manifest.",
        "strict": True,
        "input_schema": {
            "type": "object",
            "additionalProperties": False,
            "properties": {"lot_code": {"type": "string"}},
            "required": ["lot_code"],
        },
    },
    {
        "name": "check_availability",
        "description": "Whether a given number of pieces can be ordered from a lot.",
        "strict": True,
        "input_schema": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "lot_code": {"type": "string"},
                "pieces": {"type": "integer"},
            },
            "required": ["lot_code", "pieces"],
        },
    },
    {
        "name": "get_order_status",
        "description": "Status of one of this buyer's own orders, by order code.",
        "strict": True,
        "input_schema": {
            "type": "object",
            "additionalProperties": False,
            "properties": {"order_code": {"type": "string"}},
            "required": ["order_code"],
        },
    },
    {
        "name": "estimate_delivery",
        "description": "Estimated courier working days from a lot's city to a buyer's city.",
        "strict": True,
        "input_schema": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "lot_code": {"type": "string"},
                "to_city": {"type": "string"},
            },
            "required": ["lot_code", "to_city"],
        },
    },
    {
        "name": "create_order_draft",
        "description": (
            "Prepare a priced order draft for the buyer to confirm. Reserves "
            "nothing and charges nothing."
        ),
        "strict": True,
        "input_schema": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "lot_code": {"type": "string"},
                "pieces": {"type": "integer"},
                "city": {"type": "string"},
            },
            "required": ["lot_code", "pieces", "city"],
        },
    },
]


def run_tool(db: Session, name: str, arguments: dict[str, Any], *, buyer_user_id: str) -> Any:
    """Dispatch one tool call.

    ``buyer_user_id`` is injected from the session and never taken from the
    model's arguments. That is the difference between an assistant that can
    read your orders and one that can read anybody's.
    """
    cleaned = {key: value for key, value in arguments.items() if value is not None}

    if name == "search_lots":
        return search_lots(db, **cleaned)
    if name == "get_lot":
        return get_lot(db, **cleaned)
    if name == "check_availability":
        return check_availability(db, **cleaned)
    if name == "get_order_status":
        cleaned.pop("buyer_user_id", None)
        return get_order_status(db, buyer_user_id=buyer_user_id, **cleaned)
    if name == "estimate_delivery":
        return estimate_delivery(db, **cleaned)
    if name == "create_order_draft":
        cleaned.pop("buyer_user_id", None)
        return create_order_draft(db, buyer_user_id=buyer_user_id, **cleaned)

    raise ValueError(f"Unknown tool {name!r}")


def now_iso() -> str:
    return datetime.now(UTC).date().isoformat()
