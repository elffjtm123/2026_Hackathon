from datetime import datetime, timezone

import jwt
from fastapi import APIRouter, Request
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.api.deps import CurrentUser, DBSession
from app.core.errors import AppError
from app.core.security import (
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    token_fingerprint,
    verify_password,
)
from app.db.models.refresh_token import RefreshToken
from app.db.models.user import User
from app.schemas.auth import (
    LoginRequest,
    RefreshRequest,
    RegisterRequest,
    TokenResponse,
    UserResponse,
)

router = APIRouter(tags=["auth"])


async def issue_tokens(user: User, request: Request, db: DBSession) -> TokenResponse:
    settings = request.app.state.settings
    access = create_access_token(user.id, settings)
    refresh = create_refresh_token(user.id, settings)
    claims = decode_token(refresh, "refresh", settings)
    db.add(
        RefreshToken(
            user_id=user.id,
            jti=str(claims.jti),
            token_hash=token_fingerprint(refresh),
            expires_at=claims.expires_at,
        )
    )
    await db.commit()
    return TokenResponse(
        access_token=access,
        refresh_token=refresh,
        expires_in=settings.access_token_minutes * 60,
        user=UserResponse.model_validate(user),
    )


@router.post("/auth/register", response_model=TokenResponse, status_code=201)
async def register(payload: RegisterRequest, request: Request, db: DBSession) -> TokenResponse:
    user = User(
        email=str(payload.email).lower(),
        password_hash=hash_password(payload.password),
        display_name=payload.display_name.strip(),
    )
    db.add(user)
    try:
        await db.flush()
    except IntegrityError as exc:
        await db.rollback()
        raise AppError("EMAIL_ALREADY_EXISTS", "이미 가입된 이메일입니다.", 409) from exc
    return await issue_tokens(user, request, db)


@router.post("/auth/login", response_model=TokenResponse)
async def login(payload: LoginRequest, request: Request, db: DBSession) -> TokenResponse:
    user = await db.scalar(select(User).where(User.email == str(payload.email).lower()))
    if user is None or not verify_password(payload.password, user.password_hash):
        raise AppError("INVALID_CREDENTIALS", "이메일 또는 비밀번호가 올바르지 않습니다.", 401)
    return await issue_tokens(user, request, db)


@router.post("/auth/refresh", response_model=TokenResponse)
async def refresh(payload: RefreshRequest, request: Request, db: DBSession) -> TokenResponse:
    try:
        claims = decode_token(payload.refresh_token, "refresh", request.app.state.settings)
    except jwt.PyJWTError as exc:
        raise AppError("INVALID_REFRESH_TOKEN", "유효하지 않은 refresh token입니다.", 401) from exc
    stored = await db.scalar(
        select(RefreshToken).where(
            RefreshToken.jti == str(claims.jti),
            RefreshToken.token_hash == token_fingerprint(payload.refresh_token),
            RefreshToken.revoked.is_(False),
        )
    )
    if stored is None or claims.expires_at <= datetime.now(timezone.utc):
        raise AppError("INVALID_REFRESH_TOKEN", "폐기되었거나 만료된 refresh token입니다.", 401)
    user = await db.get(User, claims.subject)
    if user is None:
        raise AppError("INVALID_REFRESH_TOKEN", "유효하지 않은 refresh token입니다.", 401)
    stored.revoked = True
    await db.flush()
    return await issue_tokens(user, request, db)


@router.get("/users/me", response_model=UserResponse)
async def me(user: CurrentUser) -> User:
    return user
