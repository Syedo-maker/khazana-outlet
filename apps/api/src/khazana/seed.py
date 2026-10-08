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
import random
from datetime import timedelta

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from .config import get_settings
from .db import build_engine
from .models import (
    Base,
    Brand,
    BrandExcludedCity,
    BrandMember,
    BrandPolicy,
    Category,
    ListingApproval,
    Lot,
    LotDefect,
    LotPhoto,
    ManifestLine,
    Order,
    OrderLine,
    Payment,
    ResellerProfile,
    User,
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
    PhotoKind,
    UserRole,
    VerificationStatus,
    Visibility,
)

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

    orders = _seed_orders(db, rng, lots=lots, resellers=resellers, count=8 * scale)
    counts["orders"] = len(orders)

    db.commit()
    return counts


def _wipe(db: Session) -> None:
    """Delete in dependency order. Seed data only, never run in production."""
    settings = get_settings()
    if settings.is_production:
        raise RuntimeError("Refusing to wipe data in production.")

    for model in (
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
    ):
        db.execute(delete(model))
    db.commit()


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
                        file_key=f"seed/{lot.lot_code}/{kind.value}.jpg",
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


def _seed_orders(
    db: Session,
    rng: random.Random,
    *,
    lots: list[Lot],
    resellers: list[ResellerProfile],
    count: int,
) -> list[Order]:
    sellable = [lot for lot in lots if lot.status in {LotStatus.LIVE, LotStatus.SOLD}]
    if not sellable or not resellers:
        return []

    orders: list[Order] = []
    for index in range(count):
        lot = rng.choice(sellable)
        reseller = rng.choice([r for r in resellers if r.status == VerificationStatus.VERIFIED])
        policy = db.scalars(select(BrandPolicy).where(BrandPolicy.brand_id == lot.brand_id)).one()

        pieces = (
            lot.total_pieces
            if lot.min_order_pieces == lot.total_pieces
            else rng.randint(lot.min_order_pieces, lot.total_pieces)
        )
        unit_price = max(1, lot.lot_price_pkr // lot.total_pieces)
        subtotal = pieces * unit_price
        shipping = rng.choice([0, 1_200, 2_400, 3_600])
        commission_percent = float(policy.commission_percent)
        commission = int(subtotal * commission_percent / 100)

        status = rng.choices(
            [
                OrderStatus.CONFIRMED,
                OrderStatus.DELIVERED,
                OrderStatus.SHIPPED,
                OrderStatus.PAID,
                OrderStatus.AWAITING_PAYMENT,
                OrderStatus.DISPUTED,
            ],
            weights=[0.35, 0.2, 0.15, 0.15, 0.1, 0.05],
        )[0]

        order = Order(
            order_code=f"ORD-{index + 1:05d}",
            lot_id=lot.id,
            brand_id=lot.brand_id,
            buyer_user_id=reseller.user_id,
            pieces=pieces,
            unit_price_pkr=unit_price,
            subtotal_pkr=subtotal,
            shipping_pkr=shipping,
            total_pkr=subtotal + shipping,
            commission_percent=commission_percent,
            commission_pkr=commission,
            brand_payout_pkr=subtotal - commission,
            status=status,
            delivery_city=reseller.city,
            delivery_address=f"Shop {rng.randint(1, 300)}, {reseller.city}",
            delivery_phone=f"0302000{rng.randint(0, 9999):04d}",
            confirmed_at=utcnow() if status == OrderStatus.CONFIRMED else None,
        )
        db.add(order)
        db.flush()

        db.add(
            OrderLine(
                order_id=order.id,
                brand_id=lot.brand_id,
                size="mixed",
                color="mixed",
                pieces=pieces,
                unit_price_pkr=unit_price,
            )
        )

        if status != OrderStatus.AWAITING_PAYMENT:
            db.add(
                Payment(
                    order_id=order.id,
                    method=rng.choice(
                        [
                            PaymentMethod.BANK_TRANSFER,
                            PaymentMethod.JAZZCASH,
                            PaymentMethod.EASYPAISA,
                        ]
                    ),
                    status=(
                        PaymentStatus.RELEASED
                        if status == OrderStatus.CONFIRMED
                        else PaymentStatus.HELD
                    ),
                    amount_pkr=order.total_pkr,
                    provider="sandbox",
                    provider_reference=f"SEED-{index + 1:06d}",
                    held_at=utcnow(),
                    released_at=utcnow() if status == OrderStatus.CONFIRMED else None,
                )
            )

        db.flush()
        orders.append(order)

    return orders


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
