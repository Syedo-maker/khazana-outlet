"""A reseller's own business profile, which an admin verifies."""

from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from ...core.errors import Forbidden, NotFound
from ...models import Payout, ResellerProfile, User
from ...models.enums import UserRole, VerificationStatus
from ...services import admin_service, audit_service
from ..deps import CurrentBrand, CurrentPrincipal, Db, Principal
from .admin import PayoutOut

router = APIRouter(tags=["resellers"])

# Changing who the business is means it has to be checked again.
IDENTITY_FIELDS = ("business_name", "ntn")


class ResellerProfileIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    business_name: str = Field(min_length=2, max_length=160)
    city: str = Field(min_length=2, max_length=80)
    ntn: str | None = Field(default=None, max_length=32)
    shop_address: str | None = Field(default=None, max_length=255)
    monthly_purchase_pkr: int | None = Field(default=None, ge=0)


class ResellerProfileOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    business_name: str
    city: str
    ntn: str | None
    shop_address: str | None
    monthly_purchase_pkr: int | None
    status: VerificationStatus
    review_note: str | None


def _reseller(db: Session, principal: Principal) -> User:
    user = db.get(User, principal.user_id)
    if user is None:
        raise NotFound("That account no longer exists.")
    if user.role != UserRole.RESELLER:
        raise Forbidden("This is for reseller accounts.")
    return user


@router.get(
    "/resellers/me",
    response_model=ResellerProfileOut | None,
    operation_id="resellers_my_profile",
)
def my_profile(principal: CurrentPrincipal, db: Db) -> ResellerProfile | None:
    return _reseller(db, principal).reseller_profile


@router.put(
    "/resellers/me",
    response_model=ResellerProfileOut,
    operation_id="resellers_save_profile",
)
def save_profile(body: ResellerProfileIn, principal: CurrentPrincipal, db: Db) -> ResellerProfile:
    user = _reseller(db, principal)
    values = body.model_dump()
    profile = user.reseller_profile
    if profile is None:
        profile = ResellerProfile(user_id=user.id, status=VerificationStatus.PENDING, **values)
        db.add(profile)
    else:
        identity_changed = any(getattr(profile, name) != values[name] for name in IDENTITY_FIELDS)
        for name, value in values.items():
            setattr(profile, name, value)
        if identity_changed or VerificationStatus(profile.status) == VerificationStatus.REJECTED:
            profile.status = VerificationStatus.PENDING
            profile.review_note = None
    db.flush()
    audit_service.record(
        db,
        action="reseller.profile_saved",
        entity_type="reseller_profile",
        entity_id=profile.id,
        actor_user_id=user.id,
        actor_role=user.role,
        after={"status": VerificationStatus(profile.status).value},
    )
    db.commit()
    return profile


@router.get("/payouts", response_model=list[PayoutOut], operation_id="payouts_for_brand")
def brand_payouts(principal: CurrentBrand, db: Db) -> list[Payout]:
    brand_ids = None if principal.is_admin else principal.brand_ids
    return admin_service.payouts(db, brand_ids=brand_ids)
