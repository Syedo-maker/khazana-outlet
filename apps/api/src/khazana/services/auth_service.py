"""Phone OTP login, session issue and refresh.

Three rules are enforced here and each one is tested, because every one of
them is a way real OTP systems get broken:

1. A code is single use. Consuming a challenge marks it, and a consumed
   challenge is never accepted again.
2. Attempts are capped. After ``otp_max_attempts`` wrong guesses the
   challenge is dead, so a six digit code cannot be brute forced.
3. Requests are rate limited per phone number, so an attacker cannot churn
   challenges to get a fresh attempt budget, and a stranger cannot be spammed
   with SMS at your expense.
"""

from __future__ import annotations

from datetime import timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..core.errors import Forbidden, RateLimited, Unauthenticated, ValidationFailed
from ..core.security import (
    create_access_token,
    generate_otp_code,
    hash_otp,
    hash_token,
    new_refresh_token,
    verify_otp,
)
from ..models import BrandMember, OtpChallenge, User
from ..models import Session as UserSession
from ..models.base import utcnow
from ..models.enums import OtpPurpose, UserRole

PHONE_LENGTH = 11


def normalise_phone(raw: str) -> str:
    """Accept the shapes Pakistani users actually type, store one shape.

    Handles 03001234567, 0300 1234567, 0300-1234567, +923001234567 and
    923001234567, and rejects anything else. Normalising at the boundary is
    what stops the same person becoming two accounts.
    """
    digits = "".join(ch for ch in raw if ch.isdigit())

    if digits.startswith("92") and len(digits) == 12:
        digits = "0" + digits[2:]
    elif digits.startswith("0092") and len(digits) == 14:
        digits = "0" + digits[4:]
    elif len(digits) == 10 and digits.startswith("3"):
        digits = "0" + digits

    if len(digits) != PHONE_LENGTH or not digits.startswith("03"):
        raise ValidationFailed(
            "Enter a Pakistani mobile number as 11 digits starting with 03, for example 03001234567"
        )
    return digits


def request_otp(db: Session, raw_phone: str, purpose: OtpPurpose = OtpPurpose.LOGIN) -> str | None:
    """Create a challenge and return the code only in development.

    Returning the code in development is what lets the whole login flow be
    tested and demonstrated without an SMS gateway, which does not exist until
    Phase 6. ``assert_production_ready`` refuses to boot if this is still on
    in production.
    """
    settings = get_settings()
    phone = normalise_phone(raw_phone)
    now = utcnow()

    cooldown_start = now - timedelta(seconds=settings.otp_resend_cooldown_seconds)
    recent = db.scalar(
        select(func.count())
        .select_from(OtpChallenge)
        .where(OtpChallenge.phone == phone, OtpChallenge.created_at >= cooldown_start)
    )
    if recent:
        raise RateLimited(
            f"A code was already sent. Try again in {settings.otp_resend_cooldown_seconds} seconds."
        )

    hourly = db.scalar(
        select(func.count())
        .select_from(OtpChallenge)
        .where(OtpChallenge.phone == phone, OtpChallenge.created_at >= now - timedelta(hours=1))
    )
    if hourly and hourly >= 5:
        raise RateLimited("Too many codes requested for this number. Try again later.")

    code = generate_otp_code()
    db.add(
        OtpChallenge(
            phone=phone,
            code_hash=hash_otp(phone, code),
            purpose=purpose,
            expires_at=now + timedelta(seconds=settings.otp_ttl_seconds),
        )
    )
    db.commit()

    # Phase 6 replaces this with a real SMS and WhatsApp send.
    return code if settings.otp_dev_echo else None


def verify_otp_and_login(
    db: Session,
    raw_phone: str,
    code: str,
    *,
    full_name: str | None = None,
    role: UserRole = UserRole.RESELLER,
    user_agent: str | None = None,
    ip: str | None = None,
) -> tuple[User, str, str]:
    """Consume a challenge and issue tokens.

    Creates the user on first successful verification, which removes a
    separate signup step. ``role`` only applies to that first creation; an
    existing user's role is never changed by a login.
    """
    settings = get_settings()
    phone = normalise_phone(raw_phone)
    now = utcnow()

    challenge = db.scalars(
        select(OtpChallenge)
        .where(
            OtpChallenge.phone == phone,
            OtpChallenge.consumed_at.is_(None),
            OtpChallenge.expires_at > now,
        )
        .order_by(OtpChallenge.created_at.desc())
    ).first()

    if challenge is None:
        raise Unauthenticated("That code has expired. Request a new one.")

    if challenge.attempts >= settings.otp_max_attempts:
        raise Unauthenticated("Too many incorrect attempts. Request a new code.")

    if not verify_otp(phone, code, challenge.code_hash):
        challenge.attempts += 1
        db.commit()
        raise Unauthenticated("That code is not correct.")

    challenge.consumed_at = now

    user = db.scalars(select(User).where(User.phone == phone)).first()
    if user is None:
        if role == UserRole.ADMIN:
            # An admin is never created by someone turning up with a phone
            # number. Admins are seeded or promoted by another admin.
            raise Forbidden("Admin accounts cannot be self registered.")
        user = User(
            phone=phone,
            full_name=(full_name or "").strip() or f"User {phone[-4:]}",
            role=role,
            phone_verified_at=now,
        )
        db.add(user)
        db.flush()
    else:
        if not user.is_active or user.is_deleted:
            raise Forbidden("This account is not active.")
        if user.phone_verified_at is None:
            user.phone_verified_at = now

    user.last_login_at = now
    access, refresh = issue_session(db, user, user_agent=user_agent, ip=ip)
    db.commit()
    return user, access, refresh


def brand_ids_for(db: Session, user: User) -> list[str]:
    return list(
        db.scalars(select(BrandMember.brand_id).where(BrandMember.user_id == user.id)).all()
    )


def issue_session(
    db: Session, user: User, *, user_agent: str | None = None, ip: str | None = None
) -> tuple[str, str]:
    """Return an access token and a refresh token.

    The refresh token is returned in plain text once and stored only as a
    hash, so it cannot be recovered from the database.
    """
    settings = get_settings()
    raw_refresh = new_refresh_token()
    db.add(
        UserSession(
            user_id=user.id,
            token_hash=hash_token(raw_refresh),
            expires_at=utcnow() + timedelta(days=settings.refresh_token_ttl_days),
            user_agent=(user_agent or "")[:255] or None,
            ip=ip,
        )
    )
    access = create_access_token(
        subject=user.id, role=user.role.value, brand_ids=brand_ids_for(db, user)
    )
    return access, raw_refresh


def refresh_session(
    db: Session, raw_refresh: str, *, user_agent: str | None = None, ip: str | None = None
) -> tuple[str, str]:
    """Rotate a refresh token.

    The old token is revoked as part of issuing the new one. Without rotation,
    a stolen refresh token stays valid for its full lifetime even after the
    real user has logged in again.
    """
    now = utcnow()
    session = db.scalars(
        select(UserSession).where(
            UserSession.token_hash == hash_token(raw_refresh),
            UserSession.revoked_at.is_(None),
            UserSession.expires_at > now,
        )
    ).first()
    if session is None:
        raise Unauthenticated("Please sign in again.")

    user = db.get(User, session.user_id)
    if user is None or not user.is_active or user.is_deleted:
        raise Forbidden("This account is not active.")

    session.revoked_at = now
    access, new_raw = issue_session(db, user, user_agent=user_agent, ip=ip)
    db.commit()
    return access, new_raw


def revoke_all_sessions(db: Session, user_id: str) -> int:
    """Sign a user out everywhere. Used on logout and on suspension."""
    now = utcnow()
    sessions = db.scalars(
        select(UserSession).where(UserSession.user_id == user_id, UserSession.revoked_at.is_(None))
    ).all()
    for session in sessions:
        session.revoked_at = now
    db.commit()
    return len(sessions)
