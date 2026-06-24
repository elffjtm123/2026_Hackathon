import hashlib
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Literal
from uuid import UUID, uuid4

import jwt
from pwdlib import PasswordHash

from app.core.config import Settings

password_hash = PasswordHash.recommended()


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


def _create_token(user_id: UUID, token_type: str, lifetime: timedelta, settings: Settings) -> str:
    now = datetime.now(UTC)
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
    payload = jwt.decode(
        token,
        settings.jwt_secret,
        algorithms=[settings.jwt_algorithm],
        issuer=settings.app_name,
    )
    if payload.get("type") != expected_type:
        raise jwt.InvalidTokenError("unexpected token type")
    return TokenClaims(
        subject=UUID(payload["sub"]),
        token_type=payload["type"],
        jti=UUID(payload["jti"]),
        expires_at=datetime.fromtimestamp(payload["exp"], UTC),
    )


def token_fingerprint(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def random_secret() -> str:
    return secrets.token_urlsafe(32)
