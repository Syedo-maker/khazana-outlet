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
)
from .commerce import Dispute, Order, OrderLine, Payment, Payout, Shipment
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
    "payouts",
    "shipments",
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
    "Category",
    "Dispute",
    "Embedding",
    "ListingApproval",
    "Lot",
    "LotDefect",
    "LotExcludedCity",
    "LotPhoto",
    "ManifestLine",
    "Order",
    "OrderLine",
    "OtpChallenge",
    "Payment",
    "Payout",
    "ResellerProfile",
    "Session",
    "Shipment",
    "User",
    "Vector",
    "VerificationDocument",
    "new_id",
    "utcnow",
]
