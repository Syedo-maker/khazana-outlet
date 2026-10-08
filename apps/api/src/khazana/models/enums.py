"""Enumerations used across the schema.

These are stored as strings rather than native PostgreSQL enums. Adding a
value to a native enum requires a migration and locks the type; adding one
here is a code change plus a CHECK constraint update. For a marketplace that
will gain order states and payment methods throughout Phase 3, strings are
the pragmatic choice.
"""

from __future__ import annotations

from enum import StrEnum


class UserRole(StrEnum):
    BRAND = "brand"
    RESELLER = "reseller"
    ADMIN = "admin"


class BrandMemberRole(StrEnum):
    OWNER = "owner"
    STAFF = "staff"


class VerificationStatus(StrEnum):
    PENDING = "pending"
    VERIFIED = "verified"
    REJECTED = "rejected"
    SUSPENDED = "suspended"


class DocumentType(StrEnum):
    NTN = "ntn"
    INCORPORATION = "incorporation"
    CNIC = "cnic"
    BANK_LETTER = "bank_letter"
    SALES_TAX = "sales_tax"
    OTHER = "other"


class OtpPurpose(StrEnum):
    LOGIN = "login"
    SIGNUP = "signup"
    PHONE_CHANGE = "phone_change"


class ConditionGrade(StrEnum):
    """Grades are contractual, not descriptive. See the manifest template.

    A: new, unused, with tags, no defects.
    B: new or unused, no tags, minor shelf wear, no functional defect.
    C: factory seconds or visible defects, each one itemised.
    """

    A = "A"
    B = "B"
    C = "C"


class Visibility(StrEnum):
    """Brand protection level for a lot.

    PUBLIC: anyone can see the listing and the brand name.
    PRIVATE: only verified resellers can see it at all.
    UNBRANDED: visible, but the brand name is replaced by a generic label.
    """

    PUBLIC = "public"
    PRIVATE = "private"
    UNBRANDED = "unbranded"


class LotStatus(StrEnum):
    DRAFT = "draft"
    PENDING_APPROVAL = "pending_approval"
    APPROVED = "approved"
    LIVE = "live"
    PAUSED = "paused"
    SOLD = "sold"
    WITHDRAWN = "withdrawn"
    EXPIRED = "expired"


class ApprovalAction(StrEnum):
    SUBMITTED = "submitted"
    APPROVED = "approved"
    REJECTED = "rejected"
    WITHDRAWN = "withdrawn"
    PAUSED = "paused"
    RESUMED = "resumed"


class PhotoKind(StrEnum):
    FULL_LOT = "full_lot"
    FRONT = "front"
    BACK = "back"
    LABEL = "label"
    SIZE_SPREAD = "size_spread"
    DEFECT = "defect"
    PACKAGING = "packaging"


class OrderStatus(StrEnum):
    CREATED = "created"
    AWAITING_PAYMENT = "awaiting_payment"
    PAID = "paid"
    PREPARING = "preparing"
    SHIPPED = "shipped"
    DELIVERED = "delivered"
    CONFIRMED = "confirmed"
    DISPUTED = "disputed"
    CANCELLED = "cancelled"
    REFUNDED = "refunded"


class PaymentMethod(StrEnum):
    BANK_TRANSFER = "bank_transfer"
    JAZZCASH = "jazzcash"
    EASYPAISA = "easypaisa"
    CARD = "card"
    COD = "cod"


class PaymentStatus(StrEnum):
    PENDING = "pending"
    HELD = "held"
    RELEASED = "released"
    REFUNDED = "refunded"
    FAILED = "failed"


class PayoutStatus(StrEnum):
    PENDING = "pending"
    SCHEDULED = "scheduled"
    PAID = "paid"
    FAILED = "failed"


class ShipmentStatus(StrEnum):
    PENDING_PICKUP = "pending_pickup"
    PICKED_UP = "picked_up"
    IN_TRANSIT = "in_transit"
    DELIVERED = "delivered"
    RETURNED = "returned"
    LOST = "lost"


class DisputeStatus(StrEnum):
    OPEN = "open"
    UNDER_REVIEW = "under_review"
    RESOLVED_BUYER = "resolved_buyer"
    RESOLVED_SELLER = "resolved_seller"
    WITHDRAWN = "withdrawn"


class AiFeature(StrEnum):
    """One value per AI capability in docs/ai-architecture.md.

    Cost, evals and kill switches are all keyed on this, so a new AI feature
    starts by adding a value here.
    """

    LISTING_FROM_PHOTOS = "listing_from_photos"
    MANIFEST_EXTRACT = "manifest_extract"
    PRICING = "pricing"
    RISK_SCORING = "risk_scoring"
    ASSISTANT_BUYER = "assistant_buyer"
    ASSISTANT_BRAND = "assistant_brand"
    EMBEDDING = "embedding"
    DEMAND_FORECAST = "demand_forecast"
    TRANSLATION = "translation"


class AiJobStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    BLOCKED_BY_LIMIT = "blocked_by_limit"
    SKIPPED_KILL_SWITCH = "skipped_kill_switch"


class AiMode(StrEnum):
    LIVE = "live"
    BATCH = "batch"
    OFFLINE = "offline"


class EmbeddingOwner(StrEnum):
    LOT_PHOTO = "lot_photo"
    LOT_TEXT = "lot_text"
    SEARCH_QUERY = "search_query"
