"""Lot recommendations for resellers.

A ranking, not a model call. Each candidate lot gets a score from signals a
reseller would recognise, and every recommendation carries the reasons behind
it, so "why am I seeing this" always has an answer.

Signals, strongest first:

- **Category.** The share of the buyer's past pieces in the lot's category,
  plus the categories of their saved searches.
- **Similarity.** How close the lot's text embedding is to the lots they
  bought, when embeddings exist.
- **Price.** Whether the price per piece sits near what they usually pay.
- **City.** Stock in the buyer's own city costs less to deliver.
- **Discount.** A deeper discount is a better deal, all else equal.

A buyer with no orders yet gets the cold start ranking: their city, the
discount and how new the lot is.

Visibility is the catalogue's own rule, applied in the candidate query, so a
lot the buyer could not open is never recommended.
"""

from __future__ import annotations

import math
import statistics
from dataclasses import dataclass, field
from datetime import UTC
from typing import Any

from sqlalchemy import select, true
from sqlalchemy.orm import Session, selectinload

from ..models import Category, Embedding, Lot, Order, SavedSearch, utcnow
from ..models.enums import EmbeddingOwner, OrderStatus
from . import approval_service
from .search_service import Viewer

CANDIDATES = 200
# Orders that show what a buyer wants. A cancelled order still shows interest,
# but a refunded one may mean the lot was wrong for them.
INTEREST_STATUSES = tuple(status for status in OrderStatus if status != OrderStatus.REFUNDED)

WEIGHTS = {"category": 0.35, "similarity": 0.20, "price": 0.15, "city": 0.15, "discount": 0.15}
COLD_START_WEIGHTS = {"city": 0.40, "discount": 0.40, "recency": 0.20}
FRESH_DAYS = 30


@dataclass(slots=True)
class Recommendation:
    lot: Lot
    score: float
    reasons: list[str] = field(default_factory=list)


@dataclass(slots=True)
class BuyerProfile:
    category_share: dict[str, float]
    usual_price: float | None
    bought_lot_ids: set[str]
    saved_categories: set[str]

    @property
    def has_history(self) -> bool:
        return bool(self.bought_lot_ids)


def _price(lot: Lot) -> float:
    return lot.lot_price_pkr / lot.total_pieces if lot.total_pieces else 0.0


def buyer_profile(db: Session, user_id: str) -> BuyerProfile:
    orders = list(
        db.scalars(
            select(Order).where(Order.buyer_user_id == user_id, Order.status.in_(INTEREST_STATUSES))
        )
    )
    lots = (
        {
            lot.id: lot
            for lot in db.scalars(select(Lot).where(Lot.id.in_({o.lot_id for o in orders})))
        }
        if orders
        else {}
    )

    pieces_by_category: dict[str, int] = {}
    for order in orders:
        lot = lots.get(order.lot_id)
        if lot is not None:
            pieces_by_category[lot.category_id] = (
                pieces_by_category.get(lot.category_id, 0) + order.pieces
            )
    total = sum(pieces_by_category.values())
    share = {cat: pieces / total for cat, pieces in pieces_by_category.items()} if total else {}

    prices = [order.unit_price_pkr for order in orders if order.unit_price_pkr > 0]
    saved = set()
    for row in db.scalars(select(SavedSearch).where(SavedSearch.user_id == user_id)):
        category_id = row.filters.get("category_id") if isinstance(row.filters, dict) else None
        if isinstance(category_id, str):
            saved.add(category_id)

    return BuyerProfile(
        category_share=share,
        usual_price=statistics.median(prices) if prices else None,
        bought_lot_ids=set(lots),
        saved_categories=saved,
    )


def _vectors(db: Session, lot_ids: set[str]) -> dict[str, list[float]]:
    if not lot_ids:
        return {}
    rows = db.scalars(
        select(Embedding).where(
            Embedding.owner_type == EmbeddingOwner.LOT_TEXT, Embedding.owner_id.in_(lot_ids)
        )
    )
    return {row.owner_id: list(row.vector) for row in rows}


def _cosine(a: list[float], b: list[float]) -> float:
    if len(a) != len(b) or not a:
        return 0.0
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    norm = math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(y * y for y in b))
    return dot / norm if norm else 0.0


def _price_fit(price: float, usual: float | None) -> float:
    """1 at the buyer's usual price, falling to 0 at twice or half of it."""
    if usual is None or usual <= 0 or price <= 0:
        return 0.0
    distance = abs(math.log2(price / usual))
    return max(0.0, 1.0 - distance)


def _aware_age_days(lot: Lot) -> float:
    approved = lot.approved_at
    if approved is None:
        return float(FRESH_DAYS)
    if approved.tzinfo is None:
        approved = approved.replace(tzinfo=UTC)
    return max(0.0, (utcnow() - approved).total_seconds() / 86_400)


def recommend(db: Session, *, user_id: str, viewer: Viewer, limit: int = 8) -> list[Recommendation]:
    profile = buyer_profile(db, user_id)
    candidates = list(
        db.scalars(
            select(Lot)
            .where(
                approval_service.visibility_filter(
                    role=viewer.role, reseller_is_verified=viewer.verified, city=viewer.city
                ),
                Lot.id.not_in(profile.bought_lot_ids) if profile.bought_lot_ids else true(),
            )
            .options(selectinload(Lot.photos), selectinload(Lot.manifest_lines))
            .order_by(Lot.approved_at.desc(), Lot.id)
            .limit(CANDIDATES)
        )
    )
    if not candidates:
        return []

    category_names = {c.id: c.name for c in db.scalars(select(Category))}
    city = (viewer.city or "").strip().lower()

    bought_vectors: list[list[float]] = []
    candidate_vectors: dict[str, list[float]] = {}
    if profile.has_history:
        vectors = _vectors(db, profile.bought_lot_ids | {lot.id for lot in candidates})
        bought_vectors = [vectors[i] for i in profile.bought_lot_ids if i in vectors]
        candidate_vectors = {lot.id: vectors[lot.id] for lot in candidates if lot.id in vectors}

    ranked: list[Recommendation] = []
    for lot in candidates:
        signals: dict[str, float] = {
            "city": 1.0 if city and lot.stock_city.strip().lower() == city else 0.0,
            "discount": max(0.0, min(1.0, lot.discount_percent / 100)),
        }
        reasons: list[str] = []
        category = category_names.get(lot.category_id, "this category")

        if profile.has_history or profile.saved_categories:
            share = profile.category_share.get(lot.category_id, 0.0)
            if lot.category_id in profile.saved_categories:
                share = max(share, 0.5)
            signals["category"] = share
            signals["price"] = _price_fit(_price(lot), profile.usual_price)
            vector = candidate_vectors.get(lot.id)
            signals["similarity"] = (
                max((_cosine(vector, b) for b in bought_vectors), default=0.0) if vector else 0.0
            )
            weights = WEIGHTS
            if profile.category_share.get(lot.category_id):
                reasons.append(f"You have bought {category} before")
            elif lot.category_id in profile.saved_categories:
                reasons.append(f"Matches a saved search for {category}")
            if signals["price"] >= 0.6:
                reasons.append("Priced close to what you usually pay")
            if signals["similarity"] >= 0.8:
                reasons.append("Similar to lots you bought")
        else:
            signals["recency"] = max(0.0, 1.0 - _aware_age_days(lot) / FRESH_DAYS)
            weights = COLD_START_WEIGHTS
            if signals["recency"] > 0.5:
                reasons.append("Newly listed")

        if signals["city"]:
            reasons.append(f"Stock is in {lot.stock_city}, your city")
        if lot.discount_percent >= 70:
            reasons.append(f"{round(lot.discount_percent)}% below retail")

        score = sum(weights[name] * signals.get(name, 0.0) for name in weights)
        ranked.append(Recommendation(lot=lot, score=round(score, 4), reasons=reasons))

    ranked.sort(key=lambda rec: (rec.score, rec.lot.discount_percent), reverse=True)
    return ranked[:limit]


def explain(rec: Recommendation) -> dict[str, Any]:
    return {"lot_code": rec.lot.lot_code, "score": rec.score, "reasons": rec.reasons}
