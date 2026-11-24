"""SQLAlchemy models for Khazana Outlet.

Import ``Base`` from here, never from a submodule, so that every model is
registered on the metadata before Alembic or ``create_all`` runs.
"""

from __future__ import annotations

from .ai import AiJob, AiOutput, AiResponseCache, AiSpend, Embedding
from .assistant import AssistantConversation, AssistantMessage, WhatsAppMessage
from .audit import AuditLog
from .base import Base, Vector, as_utc, new_id, utcnow
from .brand import (
    Brand,
    BrandExcludedCity,
    BrandMember,
    BrandPolicy,
    VerificationDocument,
)
from .catalog import (
    Category,
    ListingApproval,
    Lot,
    LotDefect,
    LotExcludedCity,
    LotPhoto,
    ManifestLine,
    SavedSearch,
)
from .commerce import (
    CartItem,
    Courier,
    Dispute,
    Order,
    OrderEvent,
    OrderLine,
    OrderReturn,
    Payment,
    PaymentEvent,
    Payout,
    PayoutRun,
    Shipment,
    ShipmentEvent,
    ShippingRate,
)
from .forecast import DemandForecast, LotForecast, ProductionWarning, SeasonEvent
from .identity import OtpChallenge, ResellerProfile, Session, User
from .indexes import QUERY_INDEXES
from .insight import ResaleBenchmark, ResellKit
from .negotiation import Negotiation, NegotiationMessage
from .pool import Pool, PoolMember
from .redirect import ImpactFactor, Partner, Redirection
from .review import ReviewCase
from .sizing import SizeChartRow, StandardSize

# Tables that carry a brand_id and are therefore subject to tenant isolation.
# The isolation test suite reads this list, so adding a brand owned table
# without adding it here makes that test fail, which is the point.
BRAND_SCOPED_TABLES: tuple[str, ...] = (
    "brand_policies",
    "brand_members",
    "verification_documents",
    "brand_excluded_cities",
    "lots",
    "manifest_lines",
    "lot_defects",
    "lot_photos",
    "lot_excluded_cities",
    "listing_approvals",
    "orders",
    "order_lines",
    "order_events",
    "order_returns",
    "payouts",
    "shipments",
    "shipment_events",
    "disputes",
    "negotiations",
    "negotiation_messages",
    "lot_forecasts",
    "production_warnings",
    "size_chart_rows",
    "redirections",
)

__all__ = [
    "BRAND_SCOPED_TABLES",
    "QUERY_INDEXES",
    "AiJob",
    "AiOutput",
    "AiResponseCache",
    "AiSpend",
    "AssistantConversation",
    "AssistantMessage",
    "AuditLog",
    "Base",
    "Brand",
    "BrandExcludedCity",
    "BrandMember",
    "BrandPolicy",
    "CartItem",
    "Category",
    "Courier",
    "DemandForecast",
    "Dispute",
    "Embedding",
    "ImpactFactor",
    "ListingApproval",
    "Lot",
    "LotDefect",
    "LotExcludedCity",
    "LotForecast",
    "LotPhoto",
    "ManifestLine",
    "Negotiation",
    "NegotiationMessage",
    "Order",
    "OrderEvent",
    "OrderLine",
    "OrderReturn",
    "OtpChallenge",
    "Partner",
    "Payment",
    "PaymentEvent",
    "Payout",
    "PayoutRun",
    "Pool",
    "PoolMember",
    "ProductionWarning",
    "Redirection",
    "ResaleBenchmark",
    "ResellKit",
    "ResellerProfile",
    "ReviewCase",
    "SavedSearch",
    "SeasonEvent",
    "Session",
    "Shipment",
    "ShipmentEvent",
    "ShippingRate",
    "SizeChartRow",
    "StandardSize",
    "User",
    "Vector",
    "VerificationDocument",
    "WhatsAppMessage",
    "as_utc",
    "new_id",
    "utcnow",
]
