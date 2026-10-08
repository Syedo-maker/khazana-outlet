"""Hashing, token signing and OTP codes.

Deliberate choice: this module uses only the Python standard library, no
passlib and no JWT package.

The reasoning is narrow. The two primitives needed are a slow password hash
and a signed, expiring bearer token. ``hashlib.pbkdf2_hmac`` is the former,
and an HMAC signed payload is the latter. Both are standard constructions,
both are implemented here in one small auditable file, and neither depends on
a package that breaks on a Windows wheel the week before a deadline.

What this is not: it is not a JWT. The token is opaque to the client, which
only ever stores it and sends it back. If a third party needs to verify tokens
later, swap this module for a JWT library; nothing outside it knows the
format.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
from datetime import timedelta
from typing import Any

from ..config import get_settings
from ..models.base import utcnow

PBKDF2_ROUNDS = 390_000
SALT_BYTES = 16


# ---------------------------------------------------------------- passwords


def hash_password(password: str) -> str:
    """Return a self describing hash: algorithm, rounds, salt, digest."""
    salt = secrets.token_bytes(SALT_BYTES)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, PBKDF2_ROUNDS)
    return f"pbkdf2_sha256${PBKDF2_ROUNDS}${_b64(salt)}${_b64(digest)}"


def verify_password(password: str, stored: str | None) -> bool:
    """Constant time verification. A missing hash always fails."""
    if not stored:
        return False
    try:
        algorithm, rounds_text, salt_text, digest_text = stored.split("$")
    except ValueError:
        return False
    if algorithm != "pbkdf2_sha256":
        return False
    try:
        rounds = int(rounds_text)
        salt = _unb64(salt_text)
        expected = _unb64(digest_text)
    except (ValueError, TypeError):
        return False
    candidate = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, rounds)
    return hmac.compare_digest(candidate, expected)


# --------------------------------------------------------------------- OTP


def generate_otp_code(digits: int = 6) -> str:
    """A numeric code from a cryptographically secure source.

    ``secrets`` rather than ``random``: a predictable OTP is the same as no
    OTP, and ``random`` is predictable by design.
    """
    upper = 10**digits
    return str(secrets.randbelow(upper)).zfill(digits)


def hash_otp(phone: str, code: str) -> str:
    """Hash the code bound to the phone number.

    Binding the phone into the hash means a code hash stolen from one
    challenge cannot be replayed against another number.
    """
    settings = get_settings()
    message = f"{phone}:{code}".encode()
    return hmac.new(settings.secret_key.encode(), message, hashlib.sha256).hexdigest()


def verify_otp(phone: str, code: str, stored_hash: str) -> bool:
    return hmac.compare_digest(hash_otp(phone, code), stored_hash)


# ------------------------------------------------------------------ tokens


def hash_token(raw_token: str) -> str:
    """Hash a refresh token for storage.

    Refresh tokens are stored hashed for the same reason passwords are: a
    leaked sessions table should not let anyone resume a session. A fast hash
    is correct here, because the input is 32 bytes of entropy rather than a
    guessable human secret.
    """
    settings = get_settings()
    return hmac.new(settings.secret_key.encode(), raw_token.encode(), hashlib.sha256).hexdigest()


def new_refresh_token() -> str:
    return secrets.token_urlsafe(32)


def create_access_token(
    subject: str,
    role: str,
    brand_ids: list[str] | None = None,
    expires_in: timedelta | None = None,
) -> str:
    """Sign a short lived access token.

    The brand memberships are carried in the token so that the common case,
    a brand reading its own data, needs no extra query. They are re checked
    against the database on every write, because a token issued before a
    membership was revoked must not authorise a write.
    """
    settings = get_settings()
    ttl = expires_in or timedelta(minutes=settings.access_token_ttl_minutes)
    now = utcnow()
    payload: dict[str, Any] = {
        "sub": subject,
        "role": role,
        "brands": brand_ids or [],
        "iat": int(now.timestamp()),
        "exp": int((now + ttl).timestamp()),
    }
    body = _b64(json.dumps(payload, separators=(",", ":"), sort_keys=True).encode())
    signature = _sign(body)
    return f"{body}.{signature}"


class TokenError(Exception):
    """Raised for any invalid token. The message is deliberately vague.

    Telling a caller whether a token was malformed, forged or merely expired
    gives an attacker a free oracle.
    """


def decode_access_token(token: str) -> dict[str, Any]:
    try:
        body, signature = token.split(".")
    except ValueError as exc:
        raise TokenError("invalid token") from exc

    if not hmac.compare_digest(_sign(body), signature):
        raise TokenError("invalid token")

    try:
        payload: dict[str, Any] = json.loads(_unb64(body))
    except (ValueError, TypeError) as exc:
        raise TokenError("invalid token") from exc

    exp = payload.get("exp")
    if not isinstance(exp, int) or exp < int(utcnow().timestamp()):
        raise TokenError("invalid token")

    return payload


# ----------------------------------------------------------------- helpers


def _sign(body: str) -> str:
    settings = get_settings()
    return hmac.new(settings.secret_key.encode(), body.encode(), hashlib.sha256).hexdigest()


def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _unb64(text: str) -> bytes:
    padding = "=" * (-len(text) % 4)
    return base64.urlsafe_b64decode(text + padding)
