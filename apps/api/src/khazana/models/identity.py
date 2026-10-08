"""Users, phone OTP challenges, sessions and reseller profiles."""

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
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base, SoftDeleteMixin, TimestampMixin, UUIDPrimaryKey
from .enums import OtpPurpose, UserRole, VerificationStatus

if TYPE_CHECKING:
    from .brand import BrandMember


class User(UUIDPrimaryKey, TimestampMixin, SoftDeleteMixin, Base):
    """A person. One row per phone number.

    Phone is the identity anchor rather than email, because the Pakistani
    market runs on phone numbers and WhatsApp. Email is optional and only
    used for brands who prefer it.

    Passwords are optional. The primary flow is phone OTP, so ``password_hash``
    stays null for most users. Admins get a password as a second factor.
    """

    __tablename__ = "users"

    # Stored normalised as 11 digits starting 03, validated in the schema layer.
    phone: Mapped[str] = mapped_column(String(11), unique=True, nullable=False)
    email: Mapped[str | None] = mapped_column(String(255), unique=True, default=None)
    full_name: Mapped[str] = mapped_column(String(120), nullable=False)
    role: Mapped[UserRole] = mapped_column(String(16), nullable=False)
    password_hash: Mapped[str | None] = mapped_column(String(255), default=None)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    phone_verified_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), default=None
    )
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    preferred_language: Mapped[str] = mapped_column(String(8), nullable=False, default="en")

    brand_memberships: Mapped[list[BrandMember]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    # ResellerProfile has two foreign keys to users, the owner and the admin
    # who reviewed it, so the join has to say which one it means.
    reseller_profile: Mapped[ResellerProfile | None] = relationship(
        back_populates="user",
        uselist=False,
        foreign_keys="ResellerProfile.user_id",
    )

    __table_args__ = (
        CheckConstraint("length(phone) = 11", name="phone_length"),
        CheckConstraint(
            "role in ('brand', 'reseller', 'admin')",
            name="role_valid",
        ),
        CheckConstraint(
            "preferred_language in ('en', 'ur', 'ur_roman')",
            name="language_valid",
        ),
        Index("ix_users_role_active", "role", "is_active"),
    )


class OtpChallenge(UUIDPrimaryKey, TimestampMixin, Base):
    """A pending phone verification.

    The code itself is never stored, only a hash, for the same reason
    passwords are not stored in plain text: a database dump should not let
    anyone log in as a brand owner.

    Attempts are counted and capped, and an expired or consumed challenge can
    never be reused. Those two rules are what stop OTP brute forcing, and both
    are tested.
    """

    __tablename__ = "otp_challenges"

    phone: Mapped[str] = mapped_column(String(11), nullable=False)
    code_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    purpose: Mapped[OtpPurpose] = mapped_column(String(16), nullable=False)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    request_ip: Mapped[str | None] = mapped_column(String(45), default=None)

    __table_args__ = (
        Index("ix_otp_phone_created", "phone", "created_at"),
        CheckConstraint("attempts >= 0", name="attempts_non_negative"),
    )


class Session(UUIDPrimaryKey, TimestampMixin, Base):
    """A refresh token, stored hashed so a leaked table cannot be replayed."""

    __tablename__ = "sessions"

    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    token_hash: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    user_agent: Mapped[str | None] = mapped_column(String(255), default=None)
    ip: Mapped[str | None] = mapped_column(String(45), default=None)

    __table_args__ = (Index("ix_sessions_user_revoked", "user_id", "revoked_at"),)


class ResellerProfile(UUIDPrimaryKey, TimestampMixin, SoftDeleteMixin, Base):
    """The buyer side business profile.

    Verification matters here as much as on the brand side. A private listing
    is only safe for a brand if the people who can see it are known
    businesses, so ``status`` gates visibility of private lots in Phase 3.
    """

    __tablename__ = "reseller_profiles"

    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"), unique=True, nullable=False
    )
    business_name: Mapped[str] = mapped_column(String(160), nullable=False)
    city: Mapped[str] = mapped_column(String(80), nullable=False)
    ntn: Mapped[str | None] = mapped_column(String(32), default=None)
    status: Mapped[VerificationStatus] = mapped_column(
        String(16), nullable=False, default=VerificationStatus.PENDING
    )
    monthly_purchase_pkr: Mapped[int | None] = mapped_column(Integer, default=None)
    shop_address: Mapped[str | None] = mapped_column(String(255), default=None)
    reviewed_by_user_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="SET NULL"), default=None
    )
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    review_note: Mapped[str | None] = mapped_column(String(500), default=None)

    user: Mapped[User] = relationship(back_populates="reseller_profile", foreign_keys=[user_id])

    __table_args__ = (
        UniqueConstraint("user_id", name="one_profile_per_user"),
        Index("ix_reseller_status_city", "status", "city"),
    )
