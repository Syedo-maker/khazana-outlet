"""Single use invite links: signing in without an SMS gateway.

SMS codes cost money per message, so the pilot signs people in with links an
admin creates and sends by hand, usually as a WhatsApp message from the
admin's own phone. The rules, each one tested:

1. **Single use.** Accepting a link marks it used, under a row lock, so two
   clicks at once cannot both sign in.
2. **Short lived.** A link expires after ``invite_ttl_hours`` and an admin can
   revoke it before then.
3. **Only a hash is stored.** The token is shown once, when it is made, the
   same way refresh tokens are kept.
4. **No self service admin.** Links are for resellers and brand staff. The
   first admin is created on the server with ``python -m khazana.manage``.
5. **Verification still applies.** A reseller who joins is pending until an
   admin verifies the business, and cannot order before that.
"""

from __future__ import annotations

import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Literal
from urllib.parse import quote

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..core.errors import Forbidden, NotFound, Unauthenticated, ValidationFailed
from ..core.security import hash_token
from ..legal import TERMS_VERSION
from ..models import Brand, BrandMember, Invite, ResellerProfile, User
from ..models.base import as_utc, utcnow
from ..models.enums import BrandMemberRole, InvitePurpose, UserRole, VerificationStatus
from . import audit_service
from .auth_service import issue_session, normalise_phone

InviteStatus = Literal["pending", "used", "expired", "revoked"]
INVITABLE_ROLES = frozenset({UserRole.RESELLER, UserRole.BRAND})

_NOT_VALID = "This link is not valid. Ask the Khazana team for a new one."
_USED = "This link has already been used. Ask the Khazana team for a new one."
_EXPIRED = "This link has expired. Ask the Khazana team for a new one."


@dataclass(frozen=True, slots=True)
class Accepted:
    user: User
    access_token: str
    refresh_token: str


def link_for(token: str) -> str:
    return f"{get_settings().web_base_url.rstrip('/')}/join/{token}"


def whatsapp_url(invite: Invite, link: str) -> str:
    """A click to chat link: it opens the admin's own WhatsApp with the message
    ready to send. Free, and needs no WhatsApp Business account."""
    name = (invite.full_name or "").strip()
    greeting = f"Assalam o alaikum {name}," if name else "Assalam o alaikum,"
    hours = get_settings().invite_ttl_hours
    message = (
        f"{greeting} your Khazana Outlet beta invite: {link} "
        f"It works once, for the next {hours} hours."
    )
    return f"https://wa.me/92{invite.phone[1:]}?text={quote(message)}"


def phone_hint(phone: str) -> str:
    """Enough of the number for its owner to recognise it, not enough to use."""
    return f"{phone[:4]}{'*' * (len(phone) - 6)}{phone[-2:]}"


def status_of(invite: Invite, now: datetime | None = None) -> InviteStatus:
    moment = now or utcnow()
    if invite.revoked_at is not None:
        return "revoked"
    if invite.used_at is not None:
        return "used"
    if as_utc(invite.expires_at) <= moment:
        return "expired"
    return "pending"


def create(
    db: Session,
    *,
    admin: User,
    phone: str,
    role: UserRole,
    full_name: str | None = None,
    brand_id: str | None = None,
    note: str | None = None,
    ip: str | None = None,
) -> tuple[Invite, str]:
    """Make a link for one person. Returns the invite and the raw token, which
    is never available again."""
    if role not in INVITABLE_ROLES:
        raise ValidationFailed("Invite links are for resellers and brand staff only.")
    number = normalise_phone(phone)
    if brand_id is not None:
        if role != UserRole.BRAND:
            raise ValidationFailed("Only brand staff can be invited to a brand.")
        if db.get(Brand, brand_id) is None:
            raise NotFound("That brand does not exist.")

    existing = db.scalars(select(User).where(User.phone == number)).first()
    if existing is not None and existing.role == UserRole.ADMIN:
        raise ValidationFailed(
            "Admins sign in with a link made on the server: python -m khazana.manage login-link."
        )
    token = secrets.token_urlsafe(32)
    invite = Invite(
        token_hash=hash_token(token),
        purpose=InvitePurpose.LOGIN if existing is not None else InvitePurpose.SIGNUP,
        phone=number,
        full_name=" ".join((full_name or "").split())[:120] or None,
        role=role,
        brand_id=brand_id,
        note=" ".join((note or "").split())[:300] or None,
        created_by_user_id=admin.id,
        expires_at=utcnow() + timedelta(hours=get_settings().invite_ttl_hours),
    )
    db.add(invite)
    db.flush()
    audit_service.record(
        db,
        action="invite.created",
        entity_type="invite",
        entity_id=invite.id,
        brand_id=brand_id,
        actor_user_id=admin.id,
        actor_role=admin.role,
        after={"purpose": invite.purpose.value, "role": role.value, "phone": phone_hint(number)},
        ip=ip,
    )
    return invite, token


def create_for_admin(db: Session, *, admin: User) -> str:
    """A sign in link for an admin, made on the server, never through the API."""
    token = secrets.token_urlsafe(32)
    db.add(
        Invite(
            token_hash=hash_token(token),
            purpose=InvitePurpose.LOGIN,
            phone=admin.phone,
            full_name=admin.full_name,
            role=UserRole.ADMIN,
            note="Made on the server for an admin.",
            expires_at=utcnow() + timedelta(hours=get_settings().invite_ttl_hours),
        )
    )
    db.flush()
    return link_for(token)


def find(db: Session, token: str, *, lock: bool = False) -> Invite | None:
    statement = select(Invite).where(Invite.token_hash == hash_token(token))
    if lock:
        statement = statement.with_for_update()
    return db.scalars(statement).first()


def accept(
    db: Session,
    token: str,
    *,
    accept_terms: bool,
    full_name: str | None = None,
    business_name: str | None = None,
    city: str | None = None,
    user_agent: str | None = None,
    ip: str | None = None,
) -> Accepted:
    if not accept_terms:
        raise ValidationFailed("Accept the beta terms and privacy notice to continue.")
    invite = find(db, token, lock=True)
    if invite is None:
        raise Unauthenticated(_NOT_VALID)
    state = status_of(invite)
    if state == "used":
        raise Unauthenticated(_USED)
    if state == "expired":
        raise Unauthenticated(_EXPIRED)
    if state == "revoked":
        raise Unauthenticated(_NOT_VALID)

    now = utcnow()
    user = db.scalars(select(User).where(User.phone == invite.phone)).first()
    if user is None:
        name = " ".join((full_name or invite.full_name or "").split())[:120]
        if len(name) < 2:
            raise ValidationFailed("Enter your name.")
        user = User(
            phone=invite.phone,
            full_name=name,
            role=invite.role,
            # The admin sent this link to this number by hand, which is the
            # check an SMS code would have made.
            phone_verified_at=now,
        )
        db.add(user)
        db.flush()
        if user.role == UserRole.RESELLER:
            _start_reseller_profile(db, user, business_name=business_name, city=city)
    elif not user.is_active or user.is_deleted:
        raise Forbidden("This account is not active.")

    if invite.brand_id is not None and user.role == UserRole.BRAND:
        member = db.scalars(
            select(BrandMember).where(
                BrandMember.user_id == user.id, BrandMember.brand_id == invite.brand_id
            )
        ).first()
        if member is None:
            db.add(
                BrandMember(
                    brand_id=invite.brand_id, user_id=user.id, role_in_brand=BrandMemberRole.STAFF
                )
            )
            db.flush()

    invite.used_at = now
    invite.used_by_user_id = user.id
    user.terms_version = TERMS_VERSION
    user.terms_accepted_at = now
    user.last_login_at = now
    access, refresh = issue_session(db, user, user_agent=user_agent, ip=ip)
    audit_service.record(
        db,
        action="invite.accepted",
        entity_type="invite",
        entity_id=invite.id,
        brand_id=invite.brand_id,
        actor_user_id=user.id,
        actor_role=user.role,
        after={"purpose": invite.purpose.value, "terms_version": TERMS_VERSION},
        ip=ip,
        user_agent=user_agent,
    )
    db.flush()
    return Accepted(user=user, access_token=access, refresh_token=refresh)


def revoke(db: Session, *, invite_id: str, admin: User, ip: str | None = None) -> Invite:
    invite = db.get(Invite, invite_id)
    if invite is None:
        raise NotFound("That invite does not exist.")
    if status_of(invite) == "pending":
        invite.revoked_at = utcnow()
        db.flush()
        audit_service.record(
            db,
            action="invite.revoked",
            entity_type="invite",
            entity_id=invite.id,
            brand_id=invite.brand_id,
            actor_user_id=admin.id,
            actor_role=admin.role,
            ip=ip,
        )
    return invite


def list_invites(db: Session, *, limit: int = 100) -> list[Invite]:
    return list(db.scalars(select(Invite).order_by(Invite.created_at.desc()).limit(limit)).all())


def _start_reseller_profile(
    db: Session, user: User, *, business_name: str | None, city: str | None
) -> None:
    """The business details, pending an admin's check. Without them the
    reseller adds them on the business profile page, as before."""
    name = " ".join((business_name or "").split())
    town = " ".join((city or "").split())
    if len(name) < 2 or len(town) < 2:
        return
    db.add(
        ResellerProfile(
            user_id=user.id,
            business_name=name[:160],
            city=town[:80],
            status=VerificationStatus.PENDING,
        )
    )
    db.flush()
