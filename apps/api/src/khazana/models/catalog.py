"""Categories, lots, manifests, defects, photographs and the approval trail.

The manifest is the heart of this schema. Buyers trust or reject a lot on the
accuracy of its manifest, so the size and colour breakdown is a set of rows
with a hard rule: the sum of the lines must equal the stated total pieces.

That rule is enforced in three places on purpose, because each one catches a
different class of mistake:

1. The API layer, so a brand gets a clear error message.
2. A database trigger, added in the initial migration, so a background job or
   a direct SQL fix cannot leave a lot inconsistent.
3. A test, so neither of the above can be removed quietly.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base, SoftDeleteMixin, TimestampMixin, UUIDPrimaryKey
from .enums import ApprovalAction, ConditionGrade, LotStatus, PhotoKind, Visibility

if TYPE_CHECKING:
    from .brand import Brand


class Category(UUIDPrimaryKey, TimestampMixin, Base):
    """Two level taxonomy. Also the fixed list the AI classifier must map into.

    The AI never invents a category. The photo to listing feature is given
    this table in its prompt and must return one of these slugs, which is why
    the taxonomy lives in the database rather than in a prompt string.
    """

    __tablename__ = "categories"

    parent_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("categories.id", ondelete="RESTRICT"), default=None
    )
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    slug: Mapped[str] = mapped_column(String(120), unique=True, nullable=False)
    # Categories with a shelf life need an expiry date on the lot. Cosmetics
    # is the obvious case, and the category scoring model flags it as a risk.
    requires_expiry: Mapped[bool] = mapped_column(nullable=False, default=False)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    children: Mapped[list[Category]] = relationship()

    __table_args__ = (Index("ix_categories_parent", "parent_id"),)


class Lot(UUIDPrimaryKey, TimestampMixin, SoftDeleteMixin, Base):
    """A quantity of one product offered as a single unit of sale."""

    __tablename__ = "lots"
    __mapper_args__ = {"version_id_col": None}  # replaced below

    lot_code: Mapped[str] = mapped_column(String(24), unique=True, nullable=False)
    brand_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("brands.id", ondelete="CASCADE"), nullable=False
    )
    category_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("categories.id", ondelete="RESTRICT"), nullable=False
    )

    title: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, default=None)
    season: Mapped[str | None] = mapped_column(String(40), default=None)
    condition_grade: Mapped[ConditionGrade] = mapped_column(String(1), nullable=False)

    total_pieces: Mapped[int] = mapped_column(Integer, nullable=False)
    retail_price_per_piece_pkr: Mapped[int] = mapped_column(Integer, nullable=False)
    lot_price_pkr: Mapped[int] = mapped_column(Integer, nullable=False)
    min_order_pieces: Mapped[int] = mapped_column(Integer, nullable=False)

    stock_city: Mapped[str] = mapped_column(String(80), nullable=False)
    weight_kg: Mapped[float | None] = mapped_column(Numeric(8, 2), default=None)
    cartons: Mapped[int | None] = mapped_column(Integer, default=None)
    expiry_date: Mapped[date | None] = mapped_column(Date, default=None)
    available_until: Mapped[date | None] = mapped_column(Date, default=None)

    status: Mapped[LotStatus] = mapped_column(String(20), nullable=False, default=LotStatus.DRAFT)
    visibility: Mapped[Visibility] = mapped_column(String(16), nullable=False)

    # Set when the brand approves. Null means it has never been live, and the
    # listing cannot be served to a buyer. The roadmap makes this mandatory.
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    approved_by_user_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="SET NULL"), default=None
    )

    created_by_user_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="SET NULL"), default=None
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    brand: Mapped[Brand] = relationship(back_populates="lots")
    manifest_lines: Mapped[list[ManifestLine]] = relationship(
        back_populates="lot", cascade="all, delete-orphan"
    )
    defects: Mapped[list[LotDefect]] = relationship(
        back_populates="lot", cascade="all, delete-orphan"
    )
    photos: Mapped[list[LotPhoto]] = relationship(
        back_populates="lot", cascade="all, delete-orphan", order_by="LotPhoto.sort_order"
    )
    excluded_cities: Mapped[list[LotExcludedCity]] = relationship(
        back_populates="lot", cascade="all, delete-orphan"
    )
    approvals: Mapped[list[ListingApproval]] = relationship(
        back_populates="lot", cascade="all, delete-orphan", order_by="ListingApproval.created_at"
    )

    # Derived values are computed rather than stored, so they cannot drift.
    @property
    def price_per_piece_pkr(self) -> float:
        return self.lot_price_pkr / self.total_pieces if self.total_pieces else 0.0

    @property
    def discount_percent(self) -> float:
        retail_total = self.retail_price_per_piece_pkr * self.total_pieces
        if retail_total <= 0:
            return 0.0
        return round((1 - self.lot_price_pkr / retail_total) * 100, 2)

    @property
    def manifest_total(self) -> int:
        return sum(line.pieces for line in self.manifest_lines)

    @property
    def is_manifest_balanced(self) -> bool:
        """The rule buyers care about most. See the module docstring."""
        return self.manifest_total == self.total_pieces

    @property
    def is_publicly_visible(self) -> bool:
        return self.status == LotStatus.LIVE and self.approved_at is not None

    __table_args__ = (
        CheckConstraint("total_pieces > 0", name="total_pieces_positive"),
        CheckConstraint("lot_price_pkr > 0", name="lot_price_positive"),
        CheckConstraint("retail_price_per_piece_pkr > 0", name="retail_price_positive"),
        CheckConstraint(
            "min_order_pieces > 0 and min_order_pieces <= total_pieces",
            name="min_order_within_lot",
        ),
        CheckConstraint(
            "lot_price_pkr <= retail_price_per_piece_pkr * total_pieces",
            name="lot_price_not_above_retail",
        ),
        CheckConstraint("condition_grade in ('A', 'B', 'C')", name="grade_valid"),
        CheckConstraint(
            "visibility in ('public', 'private', 'unbranded')", name="visibility_valid"
        ),
        # A lot can only be live if it has been approved. This is the brand
        # protection promise expressed as a database constraint.
        CheckConstraint(
            "status <> 'live' or approved_at is not null",
            name="live_requires_approval",
        ),
        Index("ix_lots_brand_status", "brand_id", "status"),
        Index("ix_lots_browse", "status", "visibility", "category_id"),
        Index("ix_lots_city", "stock_city"),
    )


Lot.__mapper_args__ = {"version_id_col": Lot.__table__.c.version}


class ManifestLine(UUIDPrimaryKey, TimestampMixin, Base):
    """One size and colour combination inside a lot.

    ``brand_id`` is denormalised here deliberately, so a tenant isolation
    policy or query never needs to join through ``lots``.
    """

    __tablename__ = "manifest_lines"

    lot_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("lots.id", ondelete="CASCADE"), nullable=False
    )
    brand_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("brands.id", ondelete="CASCADE"), nullable=False
    )
    size: Mapped[str] = mapped_column(String(32), nullable=False)
    color: Mapped[str] = mapped_column(String(48), nullable=False)
    pieces: Mapped[int] = mapped_column(Integer, nullable=False)

    lot: Mapped[Lot] = relationship(back_populates="manifest_lines")

    __table_args__ = (
        UniqueConstraint("lot_id", "size", "color", name="one_line_per_size_colour"),
        CheckConstraint("pieces > 0", name="pieces_positive"),
        Index("ix_manifest_lot", "lot_id"),
    )


class LotDefect(UUIDPrimaryKey, TimestampMixin, Base):
    """An itemised defect. Required for grade C, allowed on any grade.

    Honesty here is a commercial feature, not a legal formality: an
    unmentioned defect found by a buyer loses that buyer permanently.
    """

    __tablename__ = "lot_defects"

    lot_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("lots.id", ondelete="CASCADE"), nullable=False
    )
    brand_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("brands.id", ondelete="CASCADE"), nullable=False
    )
    issue: Mapped[str] = mapped_column(String(255), nullable=False)
    pieces_affected: Mapped[int] = mapped_column(Integer, nullable=False)
    photo_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("lot_photos.id", ondelete="SET NULL"), default=None
    )

    lot: Mapped[Lot] = relationship(back_populates="defects")

    __table_args__ = (
        CheckConstraint("pieces_affected > 0", name="defect_pieces_positive"),
        Index("ix_defects_lot", "lot_id"),
    )


class LotPhoto(UUIDPrimaryKey, TimestampMixin, Base):
    """A photograph, and the source of truth for the AI listing feature.

    ``bytes_stored`` and the dimensions are recorded because image tokens
    dominate the cost of the photo to listing call. Without these numbers you
    cannot tell whether the compression step is working.
    """

    __tablename__ = "lot_photos"

    lot_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("lots.id", ondelete="CASCADE"), nullable=False
    )
    brand_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("brands.id", ondelete="CASCADE"), nullable=False
    )
    file_key: Mapped[str] = mapped_column(String(500), nullable=False)
    kind: Mapped[PhotoKind] = mapped_column(String(24), nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    width: Mapped[int | None] = mapped_column(Integer, default=None)
    height: Mapped[int | None] = mapped_column(Integer, default=None)
    bytes_stored: Mapped[int | None] = mapped_column(Integer, default=None)
    # True once the compressed, model ready derivative has been generated.
    is_optimised: Mapped[bool] = mapped_column(nullable=False, default=False)

    lot: Mapped[Lot] = relationship(back_populates="photos")

    __table_args__ = (Index("ix_photos_lot_order", "lot_id", "sort_order"),)


class LotExcludedCity(UUIDPrimaryKey, TimestampMixin, Base):
    """Per lot region lock, overriding the brand default."""

    __tablename__ = "lot_excluded_cities"

    lot_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("lots.id", ondelete="CASCADE"), nullable=False
    )
    brand_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("brands.id", ondelete="CASCADE"), nullable=False
    )
    city: Mapped[str] = mapped_column(String(80), nullable=False)

    lot: Mapped[Lot] = relationship(back_populates="excluded_cities")

    __table_args__ = (UniqueConstraint("lot_id", "city", name="one_exclusion_per_city_per_lot"),)


class ListingApproval(UUIDPrimaryKey, TimestampMixin, Base):
    """Append only record of every approval decision on a lot.

    This table is never updated and never deleted. It is the evidence a brand
    is promised: who approved what, when, and at which protection level. The
    initial migration adds a trigger that blocks UPDATE and DELETE, because an
    audit trail that can be edited is not an audit trail.
    """

    __tablename__ = "listing_approvals"

    lot_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("lots.id", ondelete="CASCADE"), nullable=False
    )
    brand_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("brands.id", ondelete="CASCADE"), nullable=False
    )
    action: Mapped[ApprovalAction] = mapped_column(String(16), nullable=False)
    actor_user_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="SET NULL"), default=None
    )
    actor_role: Mapped[str] = mapped_column(String(16), nullable=False)
    visibility_at_action: Mapped[Visibility] = mapped_column(String(16), nullable=False)
    note: Mapped[str | None] = mapped_column(String(500), default=None)
    # The exact listing payload at the moment of approval, so a later edit
    # cannot change what the brand actually agreed to.
    snapshot: Mapped[dict[str, object] | None] = mapped_column(default=None)

    lot: Mapped[Lot] = relationship(back_populates="approvals")

    __table_args__ = (Index("ix_approvals_lot_created", "lot_id", "created_at"),)
