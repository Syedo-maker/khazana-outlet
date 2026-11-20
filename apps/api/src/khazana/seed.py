"""Synthetic marketplace generator.

    python -m khazana.seed              # create if empty
    python -m khazana.seed --reset      # wipe and recreate
    python -m khazana.seed --scale 3    # three times the volume

This exists because of roadmap rule 2: the platform is built before any real
brand joins, so every phase is developed and demonstrated against a realistic
dataset rather than an empty screen. Empty states hide layout bugs, hide slow
queries, and make a demonstration useless.

The data is deterministic. The same seed produces the same marketplace, so a
screenshot in the documentation stays accurate and a failing test can be
reproduced.

Nothing here is real. Brand names are invented and marked as synthetic, so
this data can never be mistaken for a genuine brand relationship.
"""

from __future__ import annotations

import argparse
import io
import random
from datetime import timedelta

from PIL import Image, ImageDraw
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from .ai import embeddings, images, logo_regions
from .ai.evals import logo_scenes
from .config import get_settings
from .core.errors import AppError
from .db import build_engine
from .models import (
    AssistantConversation,
    AssistantMessage,
    Base,
    Brand,
    BrandExcludedCity,
    BrandMember,
    BrandPolicy,
    CartItem,
    Category,
    Courier,
    Dispute,
    Embedding,
    ListingApproval,
    Lot,
    LotDefect,
    LotPhoto,
    ManifestLine,
    Order,
    OrderEvent,
    OrderLine,
    OrderReturn,
    OtpChallenge,
    Payment,
    PaymentEvent,
    Payout,
    PayoutRun,
    ResaleBenchmark,
    ResellerProfile,
    SavedSearch,
    Shipment,
    ShipmentEvent,
    ShippingRate,
    User,
    WhatsAppMessage,
)
from .models.base import utcnow
from .models.enums import (
    ApprovalAction,
    BrandMemberRole,
    ConditionGrade,
    LotStatus,
    OrderStatus,
    PaymentMethod,
    PaymentStatus,
    PayoutStatus,
    PhotoKind,
    UserRole,
    VerificationStatus,
    Visibility,
)
from .services import (
    logistics_service,
    order_service,
    payment_service,
    photo_protection_service,
    search_index,
)
from .storage import put_object

SEED = 42

CITIES = [
    "Karachi",
    "Lahore",
    "Faisalabad",
    "Rawalpindi",
    "Multan",
    "Gujranwala",
    "Peshawar",
    "Sialkot",
    "Hyderabad",
    "Quetta",
]

CATEGORIES: list[tuple[str, str, list[tuple[str, str]], bool]] = [
    (
        "Apparel",
        "apparel",
        [
            ("Womenswear stitched", "womenswear-stitched"),
            ("Unstitched fabric", "unstitched-fabric"),
            ("Menswear", "menswear"),
            ("Kidswear", "kidswear"),
        ],
        False,
    ),
    ("Footwear", "footwear", [("Shoes", "shoes"), ("Sandals", "sandals")], False),
    (
        "Home textiles",
        "home-textiles",
        [("Bedsheets", "bedsheets"), ("Towels", "towels")],
        False,
    ),
    ("Stationery", "stationery", [("Pens", "pens"), ("Notebooks", "notebooks")], False),
    ("Cosmetics", "cosmetics", [("Skincare", "skincare"), ("Makeup", "makeup")], True),
    ("Other", "other", [], False),
]

# Invented names. The suffix is deliberate so that nobody can mistake seed
# data for a real brand that agreed to anything.
SYNTHETIC_BRANDS = [
    ("Meher Textiles (sample)", "meher-textiles-sample", "Lahore"),
    ("Sahil Apparel (sample)", "sahil-apparel-sample", "Karachi"),
    ("Noor Home (sample)", "noor-home-sample", "Faisalabad"),
    ("Kalam Stationers (sample)", "kalam-stationers-sample", "Karachi"),
    ("Rafiq Footwear (sample)", "rafiq-footwear-sample", "Sialkot"),
]

SIZES_APPAREL = ["XS", "S", "M", "L", "XL", "XXL"]
SIZES_FOOTWEAR = ["39", "40", "41", "42", "43", "44"]
SIZES_FLAT = ["One size"]
COLORS = [
    "black",
    "white",
    "navy",
    "beige",
    "maroon",
    "olive",
    "sky blue",
    "pink",
    "grey",
    "mustard",
]
SEASONS = ["Summer 2025", "Winter 2025", "Summer 2026", "Eid 2026"]


def seed(db: Session, *, scale: int = 1, reset: bool = False) -> dict[str, int]:
    # Not cryptographic, and must be reproducible: the same seed has to
    # produce the same marketplace so documentation screenshots stay true.
    rng = random.Random(SEED)  # noqa: S311

    if reset:
        _wipe(db)

    if db.scalar(select(Brand).limit(1)) is not None:
        print("Database already has brands. Use --reset to rebuild.")
        return {}

    counts: dict[str, int] = {}

    categories = _seed_categories(db)
    counts["categories"] = len(categories)

    admin = _seed_admin(db)
    counts["admins"] = 1

    brands = _seed_brands(db, rng, admin_id=admin.id)
    counts["brands"] = len(brands)

    resellers = _seed_resellers(db, rng, count=12 * scale)
    counts["resellers"] = len(resellers)

    lots = _seed_lots(db, rng, brands=brands, categories=categories, per_brand=6 * scale)
    counts["lots"] = len(lots)
    counts["manifest_lines"] = len(db.scalars(select(ManifestLine.id)).all())

    _seed_logistics(db)
    counts["resale_benchmarks"] = _seed_benchmarks(db, categories)
    counts["photos"] = _seed_photos(db, rng, lots)
    counts["embeddings"] = _index_lots(db, lots, categories)
    db.flush()

    history = _seed_sold_history(db, rng, lots=lots, resellers=resellers)
    activity = _seed_activity(db, rng, lots=lots, resellers=resellers, count=8 * scale)
    counts["orders"] = len(history) + len(activity)

    db.commit()
    return counts


def _index_lots(db: Session, lots: list[Lot], categories: dict[str, Category]) -> int:
    """Build the text vector for every seeded lot.

    Without this the embeddings table is empty after a seed, so semantic
    search answers every query with no hits and weeks 12 and 13 cannot be
    sense checked against anything. The audit found exactly that.

    Costs nothing and calls nothing external. Vectors come from the configured
    embedding provider, which is a local deterministic hash unless
    EMBEDDING_SERVICE_URL points at a self hosted model. Neither path touches
    the Anthropic API, which has no embeddings endpoint at all.

    Be clear about what this does and does not buy. With the default hashing
    provider the pipeline, the dimensions, the pgvector index and the ranking
    query are all exercised end to end, which is what makes the feature
    testable. The ordering is not semantically meaningful, because a hash of
    the words is not a model of their meaning. Judging result quality needs a
    real embedding service, and the provider interface is there so that is a
    setting rather than a rewrite.

    Live lots are indexed the way a real go live does it, photographs included
    unless the lot is unbranded.
    """
    by_id = {category.id: category.name for category in categories.values()}
    indexed = 0
    for lot in lots:
        if lot.status == LotStatus.LIVE:
            search_index.index_live_lot(db, lot)
        else:
            embeddings.index_lot(db, lot, category_name=by_id.get(lot.category_id))
        indexed += 1
    return indexed


def _wipe(db: Session) -> None:
    """Clear seeded data. Development only, never production.

    Two paths, because the append only tables behave differently.

    On PostgreSQL, `listing_approvals` and `audit_log` carry a trigger that
    rejects DELETE, which is exactly what they are for: history is not
    editable. TRUNCATE is a different operation and is not caught by that
    trigger, which is the right escape hatch for rebuilding a development
    database. The guarantee is intact, because nothing in the application can
    truncate.

    On SQLite, used by the tests, there are no triggers and DELETE is fine.
    """
    settings = get_settings()
    if settings.is_production:
        raise RuntimeError("Refusing to wipe data in production.")

    models = (
        ResaleBenchmark,
        OtpChallenge,
        WhatsAppMessage,
        AssistantMessage,
        AssistantConversation,
        CartItem,
        SavedSearch,
        Embedding,
        ShipmentEvent,
        Shipment,
        ShippingRate,
        Courier,
        Dispute,
        Payout,
        PayoutRun,
        PaymentEvent,
        OrderEvent,
        OrderReturn,
        OrderLine,
        Payment,
        Order,
        ListingApproval,
        LotDefect,
        LotPhoto,
        ManifestLine,
        Lot,
        BrandExcludedCity,
        BrandPolicy,
        BrandMember,
        Brand,
        ResellerProfile,
        User,
        Category,
    )

    if db.bind is not None and db.bind.dialect.name == "postgresql":
        from sqlalchemy import text

        # One statement, so foreign keys between these tables never block it.
        # audit_log is included because seeding writes to it and a rebuilt
        # database should not carry the previous run's history.
        tables = [model.__tablename__ for model in models]
        tables.append("audit_log")
        db.execute(text(f"TRUNCATE TABLE {', '.join(tables)} RESTART IDENTITY CASCADE"))
        db.commit()
        return

    for model in models:
        db.execute(delete(model))
    db.commit()


def _seed_benchmarks(db: Session, categories: dict[str, Category]) -> int:
    """Resale assumptions for the profit helper. Illustrative, not market data.

    The fallback row is what migration 0008 writes; a reset truncates it, so
    the seed puts it back. Two category rows show how specific rows win.
    """
    rows: list[tuple[str | None, str | None, int, int, int, str]] = [
        (None, None, 35, 45, 55, "Platform default. Replace with market data.")
    ]
    first = next(iter(categories.values()), None)
    if first is not None:
        rows.append((first.id, None, 40, 50, 60, "Illustrative category benchmark."))
        rows.append((first.id, "Karachi", 42, 52, 62, "Illustrative city benchmark."))
    existing = {(r.category_id, r.city) for r in db.scalars(select(ResaleBenchmark))}
    added = 0
    for category_id, city, low, typical, high, note in rows:
        if (category_id, city) in existing:
            continue
        db.add(
            ResaleBenchmark(
                category_id=category_id,
                city=city,
                low_percent=low,
                typical_percent=typical,
                high_percent=high,
                note=note,
            )
        )
        added += 1
    db.flush()
    return added


def _seed_categories(db: Session) -> dict[str, Category]:
    created: dict[str, Category] = {}
    for order, (name, slug, children, needs_expiry) in enumerate(CATEGORIES):
        parent = Category(name=name, slug=slug, sort_order=order, requires_expiry=needs_expiry)
        db.add(parent)
        db.flush()
        created[slug] = parent
        for child_order, (child_name, child_slug) in enumerate(children):
            child = Category(
                name=child_name,
                slug=child_slug,
                parent_id=parent.id,
                sort_order=child_order,
                requires_expiry=needs_expiry,
            )
            db.add(child)
            db.flush()
            created[child_slug] = child
    return created


def _seed_admin(db: Session) -> User:
    admin = User(
        phone="03000000001",
        full_name="Platform Admin (sample)",
        role=UserRole.ADMIN,
        email="admin@example.invalid",
        phone_verified_at=utcnow(),
    )
    db.add(admin)
    db.flush()
    return admin


def _seed_brands(db: Session, rng: random.Random, *, admin_id: str) -> list[Brand]:
    brands: list[Brand] = []
    for index, (name, slug, city) in enumerate(SYNTHETIC_BRANDS):
        owner = User(
            phone=f"0301000{index:04d}",
            full_name=f"{name.split()[0]} Owner",
            role=UserRole.BRAND,
            phone_verified_at=utcnow(),
            preferred_language=rng.choice(["en", "ur_roman"]),
        )
        db.add(owner)
        db.flush()

        brand = Brand(
            name=name,
            legal_name=f"{name} Private Limited",
            slug=slug,
            city=city,
            status=VerificationStatus.VERIFIED if index < 4 else VerificationStatus.PENDING,
            unbranded_label=rng.choice(
                [
                    "leading Pakistani lawn brand",
                    "well known Karachi footwear label",
                    "established home textile brand",
                ]
            ),
            contact_phone=owner.phone,
            reviewed_by_user_id=admin_id if index < 4 else None,
            reviewed_at=utcnow() if index < 4 else None,
        )
        db.add(brand)
        db.flush()

        # Every brand gets different terms on purpose, which is the whole
        # point of policy as data: the seed proves the system handles it.
        db.add(
            BrandPolicy(
                brand_id=brand.id,
                commission_percent=rng.choice([10, 12, 15, 18]),
                payout_terms_days=rng.choice([3, 7, 14]),
                min_lot_value_pkr=rng.choice([15_000, 25_000, 50_000]),
                min_discount_percent=rng.choice([40, 50, 60]),
                max_discount_percent=rng.choice([80, 85, 90]),
                default_visibility=rng.choice(
                    [Visibility.PRIVATE, Visibility.UNBRANDED, Visibility.PUBLIC]
                ),
                allow_cod=rng.random() < 0.3,
                allow_part_lot_orders=rng.random() < 0.5,
                auto_apply_ai_draft=rng.random() < 0.2,
            )
        )
        db.add(
            BrandMember(brand_id=brand.id, user_id=owner.id, role_in_brand=BrandMemberRole.OWNER)
        )
        # A brand with its own stores excludes those cities by default.
        for excluded in rng.sample(CITIES, k=rng.choice([0, 1, 2])):
            db.add(
                BrandExcludedCity(brand_id=brand.id, city=excluded, reason="Own retail presence")
            )
        db.flush()
        brands.append(brand)
    return brands


def _seed_resellers(db: Session, rng: random.Random, *, count: int) -> list[ResellerProfile]:
    profiles: list[ResellerProfile] = []
    for index in range(count):
        user = User(
            phone=f"0302000{index:04d}",
            full_name=f"Reseller {index + 1}",
            role=UserRole.RESELLER,
            phone_verified_at=utcnow(),
            preferred_language=rng.choice(["en", "ur", "ur_roman"]),
        )
        db.add(user)
        db.flush()
        profile = ResellerProfile(
            user_id=user.id,
            business_name=f"Shop {index + 1} (sample)",
            city=rng.choice(CITIES),
            status=(VerificationStatus.VERIFIED if index % 3 != 2 else VerificationStatus.PENDING),
            monthly_purchase_pkr=rng.choice([50_000, 150_000, 400_000, 900_000]),
        )
        db.add(profile)
        db.flush()
        profiles.append(profile)
    return profiles


def _seed_lots(
    db: Session,
    rng: random.Random,
    *,
    brands: list[Brand],
    categories: dict[str, Category],
    per_brand: int,
) -> list[Lot]:
    sellable = [
        slug
        for slug in categories
        if slug not in {"apparel", "footwear", "home-textiles", "stationery", "cosmetics", "other"}
    ]
    lots: list[Lot] = []
    counter = 0

    for brand in brands:
        policy = db.scalars(select(BrandPolicy).where(BrandPolicy.brand_id == brand.id)).one()

        for _ in range(per_brand):
            counter += 1
            slug = rng.choice(sellable)
            category = categories[slug]

            if slug in {"shoes", "sandals"}:
                sizes = SIZES_FOOTWEAR
            elif slug in {"bedsheets", "towels", "pens", "notebooks", "unstitched-fabric"}:
                sizes = SIZES_FLAT
            else:
                sizes = SIZES_APPAREL

            # Build the manifest first, then derive the total from it, which
            # guarantees the sum rule holds. Doing it the other way round is
            # how real systems end up with unbalanced manifests.
            chosen_sizes = rng.sample(sizes, k=min(len(sizes), rng.randint(2, 4)))
            chosen_colors = rng.sample(COLORS, k=rng.randint(1, 3))
            lines = [
                (size, color, rng.randint(5, 90))
                for size in chosen_sizes
                for color in chosen_colors
            ]
            total_pieces = sum(pieces for _, _, pieces in lines)

            retail = rng.choice([450, 900, 1_200, 2_000, 3_500, 5_500])
            discount = rng.uniform(
                float(policy.min_discount_percent), float(policy.max_discount_percent)
            )
            lot_price = max(1, int(retail * total_pieces * (1 - discount / 100)))

            grade = rng.choices(
                [ConditionGrade.A, ConditionGrade.B, ConditionGrade.C],
                weights=[0.5, 0.35, 0.15],
            )[0]

            status = rng.choices(
                [
                    LotStatus.LIVE,
                    LotStatus.LIVE,
                    LotStatus.LIVE,
                    LotStatus.PENDING_APPROVAL,
                    LotStatus.DRAFT,
                    LotStatus.SOLD,
                ],
                weights=[0.4, 0.15, 0.1, 0.15, 0.1, 0.1],
            )[0]
            # A brand still awaiting verification cannot have approved stock.
            if brand.status != VerificationStatus.VERIFIED and status in {
                LotStatus.LIVE,
                LotStatus.SOLD,
            }:
                status = LotStatus.PENDING_APPROVAL
            approved = status in {LotStatus.LIVE, LotStatus.SOLD}

            lot = Lot(
                lot_code=f"LOT-{counter:05d}",
                brand_id=brand.id,
                category_id=category.id,
                title=f"{category.name} lot, {rng.choice(SEASONS)}",
                description=(
                    f"Surplus {category.name.lower()} from {rng.choice(SEASONS)}. "
                    f"Condition grade {grade.value}. Stock held in {brand.city}."
                ),
                season=rng.choice(SEASONS),
                condition_grade=grade,
                total_pieces=total_pieces,
                retail_price_per_piece_pkr=retail,
                lot_price_pkr=lot_price,
                min_order_pieces=(
                    total_pieces if not policy.allow_part_lot_orders else max(1, total_pieces // 4)
                ),
                stock_city=brand.city,
                weight_kg=round(total_pieces * rng.uniform(0.15, 0.5), 2),
                cartons=max(1, total_pieces // 60),
                available_until=(utcnow() + timedelta(days=rng.randint(14, 120))).date(),
                status=status,
                reserved_pieces=total_pieces if status == LotStatus.SOLD else 0,
                visibility=policy.default_visibility,
                approved_at=utcnow() if approved else None,
                created_by_user_id=None,
            )
            db.add(lot)
            db.flush()

            for size, color, pieces in lines:
                db.add(
                    ManifestLine(
                        lot_id=lot.id,
                        brand_id=brand.id,
                        size=size,
                        color=color,
                        pieces=pieces,
                    )
                )

            if grade == ConditionGrade.C:
                db.add(
                    LotDefect(
                        lot_id=lot.id,
                        brand_id=brand.id,
                        issue=rng.choice(
                            [
                                "light stitching irregularity",
                                "minor fabric mark",
                                "faded print on a few pieces",
                            ]
                        ),
                        pieces_affected=max(1, total_pieces // rng.randint(8, 20)),
                    )
                )

            for order_index, kind in enumerate(
                [PhotoKind.FULL_LOT, PhotoKind.FRONT, PhotoKind.BACK, PhotoKind.LABEL]
            ):
                db.add(
                    LotPhoto(
                        lot_id=lot.id,
                        brand_id=brand.id,
                        file_key=f"seed/{lot.lot_code.lower()}/{kind.value}.jpg",
                        kind=kind,
                        sort_order=order_index,
                        width=1280,
                        height=1280,
                        bytes_stored=rng.randint(80_000, 260_000),
                        is_optimised=True,
                    )
                )

            db.add(
                ListingApproval(
                    lot_id=lot.id,
                    brand_id=brand.id,
                    action=ApprovalAction.SUBMITTED,
                    actor_role="brand",
                    visibility_at_action=lot.visibility,
                    note="Seed data",
                )
            )
            if approved:
                db.add(
                    ListingApproval(
                        lot_id=lot.id,
                        brand_id=brand.id,
                        action=ApprovalAction.APPROVED,
                        actor_role="brand",
                        visibility_at_action=lot.visibility,
                        note="Seed data",
                    )
                )

            db.flush()
            lots.append(lot)

    return lots


def _seed_logistics(db: Session) -> None:
    """A courier and a nationwide rate, unless migrations already added them."""
    if db.scalar(select(Courier).limit(1)) is not None:
        return
    courier = Courier(code="sandbox", name="Sandbox courier", is_active=True, is_default=True)
    courier.rates.append(ShippingRate(base_pkr=500, per_kg_pkr=60, default_piece_grams=300))
    db.add(courier)
    db.flush()


def _owners_by_brand(db: Session) -> dict[str, User]:
    rows = db.execute(
        select(BrandMember.brand_id, User).join(User, User.id == BrandMember.user_id)
    ).all()
    return dict(rows)


def _photo_image(
    rng: random.Random, kind: PhotoKind, brand_name: str
) -> tuple[bytes, list[logo_regions.Box]]:
    """A drawn product photograph, and where its brand marks are."""
    image = Image.new("RGB", (logo_scenes.WIDTH, logo_scenes.HEIGHT), logo_scenes.BACKDROP)
    colour = (rng.randint(30, 200), rng.randint(30, 200), rng.randint(30, 200))
    marks: list[logo_regions.Box] = []
    wordmark = brand_name.split(" (")[0][:18].upper()

    if kind == PhotoKind.LABEL:
        image.paste((46, 50, 58), (0, 0, image.width, image.height))
        ImageDraw.Draw(image).rectangle((150, 330, 618, 690), fill=logo_scenes.WHITE)
        mark = logo_scenes.wordmark(wordmark, 44, logo_scenes.INK)
        marks.append(logo_scenes.stamp(image, mark, (384, 450)))
    else:
        logo_scenes.shirt(image, colour)
        if kind == PhotoKind.FRONT:
            mark = logo_scenes.wordmark(wordmark, 36, logo_scenes.WHITE)
            marks.append(logo_scenes.stamp(image, mark, (384, 330)))

    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return images.prepare(buffer.getvalue()).data, marks


def _seed_photos(db: Session, rng: random.Random, lots: list[Lot]) -> int:
    """Write real photographs, and review the ones on unbranded lots.

    Buyers can then see every seeded listing, with brand marks hidden wherever
    the brand asked not to be named.
    """
    owners = _owners_by_brand(db)
    written = 0
    for lot in lots:
        if lot.status == LotStatus.SOLD:
            continue
        brand = db.get(Brand, lot.brand_id)
        if brand is None:
            continue
        for photo in lot.photos:
            data, marks = _photo_image(rng, PhotoKind(photo.kind), brand.name)
            put_object(photo.file_key, data, "image/jpeg")
            photo.width = logo_scenes.WIDTH
            photo.height = logo_scenes.HEIGHT
            photo.bytes_stored = len(data)
            written += 1
            if lot.visibility == Visibility.UNBRANDED:
                photo_protection_service.review_photo(
                    db,
                    lot=lot,
                    photo_id=photo.id,
                    actor=owners[lot.brand_id],
                    regions=marks,
                )
        db.flush()
    return written


def _seed_sold_history(
    db: Session,
    rng: random.Random,
    *,
    lots: list[Lot],
    resellers: list[ResellerProfile],
) -> list[Order]:
    """Finished sales on the sold lots, which pricing uses as comparables."""
    verified = [r for r in resellers if r.status == VerificationStatus.VERIFIED]
    orders: list[Order] = []
    for index, lot in enumerate(lot for lot in lots if lot.status == LotStatus.SOLD):
        buyer = rng.choice(verified)
        policy = db.scalars(select(BrandPolicy).where(BrandPolicy.brand_id == lot.brand_id)).one()
        unit_price = max(1, lot.lot_price_pkr // lot.total_pieces)
        commission = int(lot.lot_price_pkr * float(policy.commission_percent) / 100)
        order = Order(
            order_code=f"ORD-H{index + 1:05d}",
            lot_id=lot.id,
            brand_id=lot.brand_id,
            buyer_user_id=buyer.user_id,
            pieces=lot.total_pieces,
            unit_price_pkr=unit_price,
            rounding_adjustment_pkr=lot.lot_price_pkr - unit_price * lot.total_pieces,
            subtotal_pkr=lot.lot_price_pkr,
            shipping_pkr=0,
            total_pkr=lot.lot_price_pkr,
            commission_percent=policy.commission_percent,
            commission_pkr=commission,
            brand_payout_pkr=lot.lot_price_pkr - commission,
            status=OrderStatus.CONFIRMED,
            payment_method=PaymentMethod.BANK_TRANSFER,
            delivery_city=buyer.city,
            delivery_address=f"Shop {rng.randint(1, 300)}, {buyer.city}",
            delivery_phone=f"0302000{rng.randint(0, 9999):04d}",
            delivered_at=utcnow(),
            confirmed_at=utcnow(),
        )
        order.payments.append(
            Payment(
                method=PaymentMethod.BANK_TRANSFER,
                status=PaymentStatus.RELEASED,
                amount_pkr=order.total_pkr,
                provider="bank_transfer",
                provider_reference=f"SEED-{index + 1:06d}",
                held_at=utcnow(),
                released_at=utcnow(),
            )
        )
        db.add(order)
        db.flush()
        db.add(
            Payout(
                order_id=order.id,
                brand_id=lot.brand_id,
                amount_pkr=order.brand_payout_pkr,
                status=PayoutStatus.PAID,
                scheduled_for=utcnow(),
                paid_at=utcnow(),
                reference=f"SEED-BATCH-{index + 1:04d}",
            )
        )
        orders.append(order)
    db.flush()
    return orders


ORDER_STAGES = (
    "awaiting_payment",
    "paid",
    "preparing",
    "shipped",
    "delivered",
    "confirmed",
    "confirmed",
    "disputed",
)


def _seed_activity(
    db: Session,
    rng: random.Random,
    *,
    lots: list[Lot],
    resellers: list[ResellerProfile],
    count: int,
) -> list[Order]:
    """Orders at every stage, created through the same code buyers use."""
    owners = _owners_by_brand(db)
    buyers = [
        profile.user for profile in resellers if profile.status == VerificationStatus.VERIFIED
    ]
    candidates = [lot for lot in lots if lot.status == LotStatus.LIVE]
    rng.shuffle(candidates)

    created: list[Order] = []
    for lot in candidates:
        if len(created) >= count:
            break
        brand = db.get(Brand, lot.brand_id)
        if brand is None or brand.status != VerificationStatus.VERIFIED:
            continue

        stage = ORDER_STAGES[len(created) % len(ORDER_STAGES)]
        rng.shuffle(buyers)
        for buyer in buyers:
            profile = buyer.reseller_profile
            if profile is None:
                continue
            method = rng.choice([PaymentMethod.JAZZCASH, PaymentMethod.EASYPAISA])
            try:
                with db.begin_nested():
                    order = order_service.place_orders(
                        db,
                        buyer=buyer,
                        purchases=[order_service.Purchase(lot_id=lot.id)],
                        delivery=order_service.Delivery(
                            city=profile.city,
                            address=f"Shop {rng.randint(1, 300)}, Main Bazaar",
                            phone=f"0302{rng.randint(0, 9_999_999):07d}",
                        ),
                        method=method,
                    )[0]
                    payment_service.ensure_payment(db, order)
                    _advance_order(db, order, stage, buyer, owners[lot.brand_id])
            except AppError:
                # This buyer cannot have this lot, usually a region lock.
                continue
            created.append(order)
            break
    return created


def _advance_order(db: Session, order: Order, stage: str, buyer: User, owner: User) -> None:
    if stage == "awaiting_payment":
        return
    payment_service.complete_sandbox_payment(db, order=order, outcome="succeeded")
    if stage == "paid":
        return
    shipment = logistics_service.book_shipment(db, order=order, actor=owner)
    if stage == "preparing":
        return
    logistics_service.advance_sandbox(db, shipment=shipment)
    if stage == "shipped":
        return
    logistics_service.advance_sandbox(db, shipment=shipment)
    logistics_service.advance_sandbox(db, shipment=shipment)
    if stage == "disputed":
        order_service.open_dispute(
            db,
            order,
            actor=buyer,
            reason="Fewer pieces than the manifest",
            detail="One carton appears to be short.",
        )
    elif stage == "confirmed":
        order_service.confirm_delivery(db, order, actor=buyer)
        if order.payout is not None:
            # Already due, so a payout run can be tried straight away.
            order.payout.scheduled_for = utcnow() - timedelta(days=1)
    db.flush()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Seed a synthetic marketplace")
    parser.add_argument("--reset", action="store_true", help="wipe existing data first")
    parser.add_argument("--scale", type=int, default=1, help="volume multiplier")
    parser.add_argument("--database-url", help="override the configured database")
    args = parser.parse_args(argv)

    engine = build_engine(args.database_url)
    Base.metadata.create_all(engine)

    with Session(engine) as db:
        counts = seed(db, scale=args.scale, reset=args.reset)

    if counts:
        print("Seeded:")
        for key, value in counts.items():
            print(f"  {key:16} {value}")
        print("\nEvery brand and shop name is synthetic and marked (sample).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
