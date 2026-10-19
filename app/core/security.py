import hashlib
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Literal
from uuid import UUID, uuid4

import jwt
from pwdlib import PasswordHash

from app.core.config import Settings

password_hash = PasswordHash.recommended()

# Every token this service issues carries these claims. Requiring them prevents a
# stripped-down token (no "exp") from being accepted indefinitely.
REQUIRED_CLAIMS = ("sub", "type", "jti", "iat", "exp", "iss")

# Verified against when the account does not exist, so login takes the same time
# for unknown and known emails (user enumeration through timing).
_DUMMY_PASSWORD_HASH = password_hash.hash("not-a-real-user-password")


@dataclass(frozen=True)
class TokenClaims:
    subject: UUID
    token_type: Literal["access", "refresh"]
    jti: UUID
    expires_at: datetime


def hash_password(password: str) -> str:
    return password_hash.hash(password)


def verify_password(password: str, encoded: str) -> bool:
    return password_hash.verify(password, encoded)


def verify_password_or_dummy(password: str, encoded: str | None) -> bool:
    """Constant-ish time credential check that also runs for unknown accounts."""
    if encoded is None:
        password_hash.verify(password, _DUMMY_PASSWORD_HASH)
        return False
    return password_hash.verify(password, encoded)


def _create_token(user_id: UUID, token_type: str, lifetime: timedelta, settings: Settings) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(user_id),
        "type": token_type,
        "jti": str(uuid4()),
        "iat": now,
        "exp": now + lifetime,
        "iss": settings.app_name,
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def create_access_token(user_id: UUID, settings: Settings) -> str:
    return _create_token(
        user_id, "access", timedelta(minutes=settings.access_token_minutes), settings
    )


def create_refresh_token(user_id: UUID, settings: Settings) -> str:
    return _create_token(user_id, "refresh", timedelta(days=settings.refresh_token_days), settings)


def decode_token(token: str, expected_type: str, settings: Settings) -> TokenClaims:
    try:
        payload = jwt.decode(
            token,
            settings.jwt_secret,
            algorithms=[settings.jwt_algorithm],
            issuer=settings.app_name,
            options={"require": list(REQUIRED_CLAIMS)},
        )
        if payload.get("type") != expected_type:
            raise jwt.InvalidTokenError("unexpected token type")
        return TokenClaims(
            subject=UUID(payload["sub"]),
            token_type=payload["type"],
            jti=UUID(payload["jti"]),
            expires_at=datetime.fromtimestamp(payload["exp"], timezone.utc),
        )
    except (KeyError, TypeError, ValueError, OverflowError, OSError) as exc:
        # Any claim that cannot be parsed is an invalid token, never a 500.
        raise jwt.InvalidTokenError("malformed token claims") from exc


def token_fingerprint(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def random_secret() -> str:
    return secrets.token_urlsafe(32)
