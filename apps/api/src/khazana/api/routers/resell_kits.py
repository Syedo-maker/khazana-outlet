"""The resell kit for a purchased order."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Response
from pydantic import BaseModel, Field

from ...core.errors import NotFound
from ...models import User
from ...services import resell_kit_service
from ..deps import CurrentPrincipal, Db, Principal

router = APIRouter(tags=["resell-kits"])


class KitIn(BaseModel):
    selling_price_pkr: int = Field(ge=1, le=1_000_000)


class PriceTagOut(BaseModel):
    size: str
    color: str
    pieces: int
    price_en: str
    price_ur: str


class KitOut(BaseModel):
    order_id: str
    lot_code: str
    selling_price_pkr: int
    caption_en: str
    caption_ur_roman: str
    caption_ur: str
    social_post: str
    whatsapp_status: str
    hashtags: list[str]
    selling_points: list[str]
    price_tags: list[PriceTagOut]
    whatsapp_catalogue: str
    photo_paths: list[str]


def _user(db: Db, principal: Principal) -> User:
    user = db.get(User, principal.user_id)
    if user is None:
        raise NotFound("That account no longer exists.")
    return user


def _out(kit: resell_kit_service.Kit) -> KitOut:
    copy: dict[str, Any] = kit.record.copy
    return KitOut(
        order_id=kit.order.id,
        lot_code=kit.lot.lot_code,
        selling_price_pkr=kit.record.selling_price_pkr,
        caption_en=str(copy.get("caption_en", "")),
        caption_ur_roman=str(copy.get("caption_ur_roman", "")),
        caption_ur=str(copy.get("caption_ur", "")),
        social_post=str(copy.get("social_post", "")),
        whatsapp_status=str(copy.get("whatsapp_status", "")),
        hashtags=[str(tag) for tag in copy.get("hashtags") or []],
        selling_points=[str(point) for point in copy.get("selling_points") or []],
        price_tags=[PriceTagOut(**tag) for tag in kit.price_tags],
        whatsapp_catalogue=kit.whatsapp_catalogue,
        photo_paths=[
            f"/orders/{kit.order.id}/resell-kit/photos/{photo_id}" for photo_id in kit.photo_ids
        ],
    )


@router.post(
    "/orders/{order_id}/resell-kit",
    response_model=KitOut,
    operation_id="resell_kit_generate",
    responses={
        402: {"description": "An AI spend cap was reached before the call was made"},
        404: {"description": "No such order for this account"},
        409: {"description": "The order is not paid, or was cancelled or refunded"},
    },
)
def generate_kit(order_id: str, body: KitIn, principal: CurrentPrincipal, db: Db) -> KitOut:
    """Write the kit for this order at the buyer's selling price, replacing any earlier one."""
    kit = resell_kit_service.generate(
        db, user=_user(db, principal), order_id=order_id, selling_price_pkr=body.selling_price_pkr
    )
    db.commit()
    return _out(kit)


@router.get(
    "/orders/{order_id}/resell-kit",
    response_model=KitOut | None,
    operation_id="resell_kit_view",
    responses={404: {"description": "No such order for this account"}},
)
def view_kit(order_id: str, principal: CurrentPrincipal, db: Db) -> KitOut | None:
    """The order's kit, or null when none has been made yet."""
    kit = resell_kit_service.find(db, user=_user(db, principal), order_id=order_id)
    return _out(kit) if kit is not None else None


@router.get(
    "/orders/{order_id}/resell-kit/photos/{photo_id}",
    operation_id="resell_kit_photo",
    response_class=Response,
)
def kit_photo(order_id: str, photo_id: str, principal: CurrentPrincipal, db: Db) -> Response:
    """A photograph of the lot as buyers may see it, cropped square for posting."""
    data = resell_kit_service.square_photo(
        db, user=_user(db, principal), order_id=order_id, photo_id=photo_id
    )
    return Response(
        content=data,
        media_type="image/jpeg",
        headers={"Cache-Control": "private, max-age=300"},
    )
