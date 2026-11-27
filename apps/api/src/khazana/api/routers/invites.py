"""Invite links: admins make them, people open them to sign in once."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Request, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from ...config import get_settings
from ...core.errors import AppError, NotFound
from ...legal import TERMS_VERSION
from ...models import Invite, User
from ...models.enums import InvitePurpose, UserRole
from ...services import invite_service
from ..deps import AdminOnly, Db, client_ip
from ..schemas import TokenPair

router = APIRouter(tags=["auth"])


class InviteIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    phone: str = Field(min_length=10, max_length=20, examples=["03001234567"])
    full_name: str | None = Field(default=None, max_length=120)
    role: Literal["reseller", "brand"]
    # Brand staff join this brand when they accept.
    brand_id: str | None = None
    note: str | None = Field(default=None, max_length=300)


class InviteOut(BaseModel):
    id: str
    purpose: InvitePurpose
    phone: str
    full_name: str | None
    role: UserRole
    brand_id: str | None
    note: str | None
    status: Literal["pending", "used", "expired", "revoked"]
    created_at: datetime
    expires_at: datetime
    used_at: datetime | None


class CreatedInviteOut(InviteOut):
    # Shown once. Only a hash is kept, so a lost link needs a new invite.
    link: str
    whatsapp_url: str


class InvitePreviewOut(BaseModel):
    valid: bool
    message: str | None = None
    purpose: InvitePurpose | None = None
    role: UserRole | None = None
    full_name: str | None = None
    phone_hint: str | None = None
    expires_at: datetime | None = None
    terms_version: str = TERMS_VERSION


class AcceptIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    accept_terms: bool
    full_name: str | None = Field(default=None, max_length=120)
    business_name: str | None = Field(default=None, max_length=160)
    city: str | None = Field(default=None, max_length=80)


def _out(invite: Invite) -> InviteOut:
    return InviteOut(
        id=invite.id,
        purpose=invite.purpose,
        phone=invite.phone,
        full_name=invite.full_name,
        role=invite.role,
        brand_id=invite.brand_id,
        note=invite.note,
        status=invite_service.status_of(invite),
        created_at=invite.created_at,
        expires_at=invite.expires_at,
        used_at=invite.used_at,
    )


def _admin(db: Session, user_id: str) -> User:
    user = db.get(User, user_id)
    if user is None:
        raise NotFound("That account no longer exists.")
    return user


@router.post(
    "/admin/invites",
    response_model=CreatedInviteOut,
    status_code=status.HTTP_201_CREATED,
    operation_id="admin_create_invite",
    tags=["admin"],
)
def create_invite(
    body: InviteIn, principal: AdminOnly, db: Db, request: Request
) -> CreatedInviteOut:
    """A single use link for one person, to send by hand. The link is in this
    response only."""
    invite, token = invite_service.create(
        db,
        admin=_admin(db, principal.user_id),
        phone=body.phone,
        role=UserRole(body.role),
        full_name=body.full_name,
        brand_id=body.brand_id,
        note=body.note,
        ip=client_ip(request),
    )
    db.commit()
    link = invite_service.link_for(token)
    return CreatedInviteOut(
        **_out(invite).model_dump(),
        link=link,
        whatsapp_url=invite_service.whatsapp_url(invite, link),
    )


@router.get(
    "/admin/invites",
    response_model=list[InviteOut],
    operation_id="admin_invites",
    tags=["admin"],
)
def list_invites(_: AdminOnly, db: Db) -> list[InviteOut]:
    return [_out(row) for row in invite_service.list_invites(db)]


@router.post(
    "/admin/invites/{invite_id}/revoke",
    response_model=InviteOut,
    operation_id="admin_revoke_invite",
    tags=["admin"],
)
def revoke_invite(invite_id: str, principal: AdminOnly, db: Db, request: Request) -> InviteOut:
    invite = invite_service.revoke(
        db, invite_id=invite_id, admin=_admin(db, principal.user_id), ip=client_ip(request)
    )
    db.commit()
    return _out(invite)


@router.get(
    "/auth/invites/{token}",
    response_model=InvitePreviewOut,
    operation_id="auth_invite_preview",
    summary="What an invite link is for, before it is used",
)
def preview_invite(token: str, db: Db) -> InvitePreviewOut:
    invite = invite_service.find(db, token)
    if invite is None:
        return InvitePreviewOut(valid=False, message="This link is not valid.")
    state = invite_service.status_of(invite)
    if state != "pending":
        return InvitePreviewOut(valid=False, message=f"This link is {state}.")
    return InvitePreviewOut(
        valid=True,
        purpose=invite.purpose,
        role=invite.role,
        full_name=invite.full_name,
        phone_hint=invite_service.phone_hint(invite.phone),
        expires_at=invite.expires_at,
    )


@router.post(
    "/auth/invites/{token}/accept",
    response_model=TokenPair,
    operation_id="auth_invite_accept",
    summary="Use an invite link once, accepting the beta terms, and sign in",
)
def accept_invite(token: str, body: AcceptIn, request: Request, db: Db) -> TokenPair:
    try:
        accepted = invite_service.accept(
            db,
            token,
            accept_terms=body.accept_terms,
            full_name=body.full_name,
            business_name=body.business_name,
            city=body.city,
            user_agent=request.headers.get("user-agent"),
            ip=client_ip(request),
        )
    except AppError as exc:
        db.rollback()
        raise exc.as_http() from exc
    db.commit()
    return TokenPair(
        access_token=accepted.access_token,
        refresh_token=accepted.refresh_token,
        expires_in_seconds=get_settings().access_token_ttl_minutes * 60,
    )
