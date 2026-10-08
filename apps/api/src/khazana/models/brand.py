"""Brands, their members, their policy configuration and their documents.

``BrandPolicy`` is the table that makes roadmap rule 1 real: commission,
discount bands, protection defaults, payout terms and lot minimums are rows,
not constants. When a brand in Phase 6 negotiates 12 percent instead of 15,
that is an UPDATE, not a release.
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base, SoftDeleteMixin, TimestampMixin, UUIDPrimaryKey
from .enums import BrandMemberRole, DocumentType, VerificationStatus, Visibility

if TYPE_CHECKING:
    from .catalog import Lot
    from .identity import User


class Brand(UUIDPrimaryKey, TimestampMixin, SoftDeleteMixin, Base):
    """A selling brand. The tenant boundary of the whole system."""

    __tablename__ = "brands"

    name: Mapped[str] = mapped_column(String(160), nullable=False)
    legal_name: Mapped[str | None] = mapped_column(String(200), default=None)
    slug: Mapped[str] = mapped_column(String(160), unique=True, nullable=False)
    ntn: Mapped[str | None] = mapped_column(String(32), default=None)
    city: Mapped[str] = mapped_column(String(80), nullable=False)
    status: Mapped[VerificationStatus] = mapped_column(
        String(16), nullable=False, default=VerificationStatus.PENDING
    )
    # The label shown in place of the real name on an unbranded listing, for
    # example "leading Pakistani lawn brand". Brand supplied, admin approved.
    unbranded_label: Mapped[str | None] = mapped_column(String(160), default=None)
    contact_phone: Mapped[str | None] = mapped_column(String(11), default=None)
    contact_email: Mapped[str | None] = mapped_column(String(255), default=None)
    reviewed_by_user_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="SET NULL"), default=None
    )
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    review_note: Mapped[str | None] = mapped_column(String(500), default=None)

    policy: Mapped[BrandPolicy] = relationship(
        back_populates="brand", uselist=False, cascade="all, delete-orphan"
    )
    members: Mapped[list[BrandMember]] = relationship(
        back_populates="brand", cascade="all, delete-orphan"
    )
    documents: Mapped[list[VerificationDocument]] = relationship(
        back_populates="brand", cascade="all, delete-orphan"
    )
    default_excluded_cities: Mapped[list[BrandExcludedCity]] = relationship(
        back_populates="brand", cascade="all, delete-orphan"
    )
    lots: Mapped[list[Lot]] = relationship(back_populates="brand")

    __table_args__ = (Index("ix_brands_status_city", "status", "city"),)


class BrandPolicy(UUIDPrimaryKey, TimestampMixin, Base):
    """Per brand commercial and protection settings.

    Nothing in this table is a constant anywhere in the codebase. Any module
    that needs a commission rate or a discount band reads it from here.
    """

    __tablename__ = "brand_policies"

    brand_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("brands.id", ondelete="CASCADE"), unique=True, nullable=False
    )

    # Commercial terms.
    commission_percent: Mapped[float] = mapped_column(Numeric(5, 2), nullable=False, default=15.00)
    payout_terms_days: Mapped[int] = mapped_column(Integer, nullable=False, default=7)
    min_lot_value_pkr: Mapped[int] = mapped_column(Integer, nullable=False, default=25_000)
    min_discount_percent: Mapped[float] = mapped_column(Numeric(5, 2), nullable=False, default=50)
    max_discount_percent: Mapped[float] = mapped_column(Numeric(5, 2), nullable=False, default=85)

    # Brand protection defaults, applied to every new lot unless overridden.
    default_visibility: Mapped[Visibility] = mapped_column(
        String(16), nullable=False, default=Visibility.PRIVATE
    )
    # Mandatory in the roadmap and therefore not nullable and defaulted true.
    # A brand may not switch off its own approval gate.
    require_brand_approval: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    allow_cod: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    allow_part_lot_orders: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    # AI behaviour per brand. Some brands will want the AI draft applied
    # automatically, most will want to review it first.
    auto_apply_ai_draft: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    ai_monthly_budget_usd: Mapped[float] = mapped_column(
        Numeric(8, 2), nullable=False, default=20.00
    )

    brand: Mapped[Brand] = relationship(back_populates="policy")

    __table_args__ = (
        CheckConstraint(
            "commission_percent >= 0 and commission_percent <= 50",
            name="commission_in_range",
        ),
        CheckConstraint(
            "min_discount_percent < max_discount_percent",
            name="discount_band_ordered",
        ),
        CheckConstraint("min_lot_value_pkr >= 0", name="min_lot_value_non_negative"),
        CheckConstraint("payout_terms_days >= 0", name="payout_terms_non_negative"),
        CheckConstraint("require_brand_approval = true", name="approval_gate_mandatory"),
    )


class BrandMember(UUIDPrimaryKey, TimestampMixin, Base):
    """Links a user to a brand. This is how tenancy is resolved at request time.

    A user can belong to more than one brand, which matters for group
    companies that run several labels, and a brand can have several staff
    users without sharing one login.
    """

    __tablename__ = "brand_members"

    brand_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("brands.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    role_in_brand: Mapped[BrandMemberRole] = mapped_column(
        String(16), nullable=False, default=BrandMemberRole.OWNER
    )

    brand: Mapped[Brand] = relationship(back_populates="members")
    user: Mapped[User] = relationship(back_populates="brand_memberships")

    __table_args__ = (
        UniqueConstraint("brand_id", "user_id", name="one_membership_per_user_per_brand"),
        Index("ix_brand_members_user", "user_id"),
    )


class VerificationDocument(UUIDPrimaryKey, TimestampMixin, Base):
    """NTN, incorporation certificate, CNIC and so on, with a review trail."""

    __tablename__ = "verification_documents"

    brand_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("brands.id", ondelete="CASCADE"), nullable=False
    )
    doc_type: Mapped[DocumentType] = mapped_column(String(24), nullable=False)
    file_key: Mapped[str] = mapped_column(String(500), nullable=False)
    original_filename: Mapped[str | None] = mapped_column(String(255), default=None)
    content_type: Mapped[str | None] = mapped_column(String(100), default=None)
    size_bytes: Mapped[int | None] = mapped_column(Integer, default=None)
    status: Mapped[VerificationStatus] = mapped_column(
        String(16), nullable=False, default=VerificationStatus.PENDING
    )
    uploaded_by_user_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="SET NULL"), default=None
    )
    reviewed_by_user_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="SET NULL"), default=None
    )
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    review_note: Mapped[str | None] = mapped_column(String(500), default=None)

    brand: Mapped[Brand] = relationship(back_populates="documents")

    __table_args__ = (Index("ix_docs_brand_status", "brand_id", "status"),)


class BrandExcludedCity(UUIDPrimaryKey, TimestampMixin, Base):
    """Default region lock for a brand.

    A brand with stores in Lahore and Karachi excludes those cities once here,
    and every new lot inherits it. A lot can still override, which is why
    there is a separate per lot table in catalog.py.
    """

    __tablename__ = "brand_excluded_cities"

    brand_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("brands.id", ondelete="CASCADE"), nullable=False
    )
    city: Mapped[str] = mapped_column(String(80), nullable=False)
    reason: Mapped[str | None] = mapped_column(String(255), default=None)

    brand: Mapped[Brand] = relationship(back_populates="default_excluded_cities")

    __table_args__ = (
        UniqueConstraint("brand_id", "city", name="one_exclusion_per_city_per_brand"),
    )
