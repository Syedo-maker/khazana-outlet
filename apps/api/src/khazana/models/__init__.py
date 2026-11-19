"""SQLAlchemy models for Khazana Outlet.

Import ``Base`` from here, never from a submodule, so that every model is
registered on the metadata before Alembic or ``create_all`` runs.
"""

from __future__ import annotations

from .ai import AiJob, AiOutput, AiSpend, Embedding
from .audit import AuditLog
from .base import Base, Vector, new_id, utcnow
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
from .identity import OtpChallenge, ResellerProfile, Session, User

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
)

__all__ = [
    "BRAND_SCOPED_TABLES",
    "AiJob",
    "AiOutput",
    "AiSpend",
    "AuditLog",
    "Base",
    "Brand",
    "BrandExcludedCity",
    "BrandMember",
    "BrandPolicy",
    "CartItem",
    "Category",
    "Courier",
    "Dispute",
    "Embedding",
    "ListingApproval",
    "Lot",
    "LotDefect",
    "LotExcludedCity",
    "LotPhoto",
    "ManifestLine",
    "Order",
    "OrderEvent",
    "OrderLine",
    "OrderReturn",
    "OtpChallenge",
    "Payment",
    "PaymentEvent",
    "Payout",
    "PayoutRun",
    "ResellerProfile",
    "SavedSearch",
    "Session",
    "Shipment",
    "ShipmentEvent",
    "ShippingRate",
    "User",
    "Vector",
    "VerificationDocument",
    "new_id",
    "utcnow",
]
