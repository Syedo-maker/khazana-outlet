"""The resell kit: what a buyer needs to sell what they just bought.

For each purchased order the kit holds captions in English, Roman Urdu and
Urdu, a social post, a WhatsApp status, price tags, a WhatsApp catalogue
text, and square photographs ready to post.

Who writes what:

- **The model** writes the words, from the facts of the order only. It is
  never given the brand's retail price, and for an unbranded lot it is never
  given the brand. It cannot repeat what it was not told.
- **Code** writes every price, size and colour: the tags and the catalogue
  list come straight from the order lines and the buyer's own selling price.
- **Photographs** are the buyer facing versions only, so brand marks that
  were blurred for an unbranded lot stay blurred.

Only the buyer who placed the order can generate or read its kit, and only
once it is paid; a cancelled or refunded order has nothing to sell.
"""

from __future__ import annotations

import io
import json
from dataclasses import dataclass
from typing import Any

from PIL import Image
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..ai.gateway import run_feature
from ..ai.schemas import ResellKitCopy
from ..core.errors import Conflict, NotFound, ValidationFailed
from ..models import Category, Lot, Order, ResellKit, User
from ..models.enums import SOLD_ORDER_STATUSES, AiFeature, ConditionGrade, OrderStatus, Visibility
from ..storage import read_object
from . import photo_protection_service

KIT_STATUSES = SOLD_ORDER_STATUSES
GRADE_MEANING = {
    ConditionGrade.A: "New, unused, with tags, no defects",
    ConditionGrade.B: "New or unused, no tags, minor shelf wear, no functional defect",
    ConditionGrade.C: "Factory seconds or visible defects, each one listed",
}
HIDDEN_BRAND = "Not to be named. Describe the product only."
SQUARE_PIXELS = 1080


@dataclass(slots=True)
class Kit:
    record: ResellKit
    order: Order
    lot: Lot
    price_tags: list[dict[str, Any]]
    whatsapp_catalogue: str
    photo_ids: list[str]


def owned_order(db: Session, *, user: User, order_id: str) -> Order:
    order = db.get(Order, order_id)
    if order is None or order.buyer_user_id != user.id:
        raise NotFound("That order does not exist.")
    return order


def _lot(db: Session, order: Order) -> Lot:
    lot = db.get(Lot, order.lot_id)
    if lot is None:
        raise NotFound("That lot no longer exists.")
    return lot


def facts_for(db: Session, order: Order, lot: Lot) -> dict[str, Any]:
    """What the model is told. Nothing about price, and no hidden brand."""
    category = db.get(Category, lot.category_id)
    brand = lot.brand.name if Visibility(lot.visibility) == Visibility.PUBLIC else HIDDEN_BRAND
    grade = ConditionGrade(lot.condition_grade)
    return {
        "title": lot.title,
        "category": category.name if category else "Clothing",
        "condition_grade": grade.value,
        "condition_meaning": GRADE_MEANING[grade],
        "sizes": sorted({line.size for line in order.lines}),
        "colours": sorted({line.color for line in order.lines}),
        "pieces": order.pieces,
        "brand": brand,
        "defects": [defect.issue for defect in lot.defects],
    }


def price_tags(order: Order, price: int) -> list[dict[str, Any]]:
    return [
        {
            "size": line.size,
            "color": line.color,
            "pieces": line.pieces,
            "price_en": f"Rs {price:,}",
            "price_ur": f"{price:,} روپے",
        }
        for line in sorted(order.lines, key=lambda item: (item.size, item.color))
    ]


def whatsapp_catalogue(copy: dict[str, Any], order: Order, price: int, shop: str) -> str:
    lines = [f"*{shop}*", "", str(copy.get("caption_ur_roman", "")), ""]
    for line in sorted(order.lines, key=lambda item: (item.size, item.color)):
        lines.append(f"- {line.size}, {line.color}: Rs {price:,}")
    lines += ["", "Order ke liye isi number par WhatsApp karein."]
    return "\n".join(lines)


def _shop(user: User) -> tuple[str, str]:
    profile = user.reseller_profile
    if profile is None:
        return user.full_name, ""
    return profile.business_name, profile.city


def generate(db: Session, *, user: User, order_id: str, selling_price_pkr: int) -> Kit:
    """Write, or rewrite, the kit for one of the buyer's paid orders."""
    order = owned_order(db, user=user, order_id=order_id)
    if OrderStatus(order.status) not in KIT_STATUSES:
        raise Conflict("A resell kit is available once the order is paid.")
    if selling_price_pkr < 1:
        raise ValidationFailed("Set the price you will sell each piece at.")
    lot = _lot(db, order)
    shop, city = _shop(user)

    result = run_feature(
        db,
        AiFeature.RESELL_KIT,
        prompt_name="resell_kit",
        prompt_values={
            "facts": json.dumps(facts_for(db, order, lot), indent=2, ensure_ascii=False),
            "selling_price_pkr": selling_price_pkr,
            "shop_name": shop,
            "shop_city": city or "Pakistan",
        },
        output_schema=ResellKitCopy,
        user_id=user.id,
        entity_type="order",
        entity_id=order.id,
    )
    copy = result.output
    assert isinstance(copy, ResellKitCopy)

    record = db.scalar(select(ResellKit).where(ResellKit.order_id == order.id))
    if record is None:
        record = ResellKit(order_id=order.id, user_id=user.id, selling_price_pkr=0, copy={})
        db.add(record)
    record.selling_price_pkr = selling_price_pkr
    record.copy = copy.model_dump()
    db.flush()
    return _assemble(db, record, order, lot, user)


def find(db: Session, *, user: User, order_id: str) -> Kit | None:
    """The kit for one of the buyer's orders, or None if none was made yet."""
    order = owned_order(db, user=user, order_id=order_id)
    record = db.scalar(select(ResellKit).where(ResellKit.order_id == order.id))
    if record is None:
        return None
    return _assemble(db, record, order, _lot(db, order), user)


def get(db: Session, *, user: User, order_id: str) -> Kit:
    order = owned_order(db, user=user, order_id=order_id)
    record = db.scalar(select(ResellKit).where(ResellKit.order_id == order.id))
    if record is None:
        raise NotFound("No resell kit has been made for this order yet.")
    return _assemble(db, record, order, _lot(db, order), user)


def _assemble(db: Session, record: ResellKit, order: Order, lot: Lot, user: User) -> Kit:
    shop, _ = _shop(user)
    return Kit(
        record=record,
        order=order,
        lot=lot,
        price_tags=price_tags(order, record.selling_price_pkr),
        whatsapp_catalogue=whatsapp_catalogue(record.copy, order, record.selling_price_pkr, shop),
        photo_ids=[photo.id for photo in photo_protection_service.buyer_photos(lot)],
    )


def square_photo(db: Session, *, user: User, order_id: str, photo_id: str) -> bytes:
    """A buyer facing photograph of the order's lot, cropped square for posting."""
    order = owned_order(db, user=user, order_id=order_id)
    lot = _lot(db, order)
    photo = next((p for p in lot.photos if p.id == photo_id), None)
    key = photo_protection_service.buyer_file_key(lot, photo) if photo else None
    if key is None:
        raise NotFound("That photograph is not available.")
    with Image.open(io.BytesIO(read_object(key))) as image:
        rgb = image.convert("RGB")
        side = min(rgb.size)
        left = (rgb.width - side) // 2
        top = (rgb.height - side) // 2
        square = rgb.crop((left, top, left + side, top + side)).resize(
            (SQUARE_PIXELS, SQUARE_PIXELS) if side >= SQUARE_PIXELS else (side, side)
        )
        out = io.BytesIO()
        square.save(out, format="JPEG", quality=88)
        return out.getvalue()
