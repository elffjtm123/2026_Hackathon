from collections.abc import AsyncIterator
from typing import Annotated

import jwt
from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.errors import AppError
from app.core.security import decode_token
from app.db.models.user import User

bearer = HTTPBearer(auto_error=False)


async def get_db(request: Request) -> AsyncIterator[AsyncSession]:
    async with request.app.state.database.sessions() as session:
        yield session


def settings_dependency(request: Request) -> Settings:
    return request.app.state.settings


async def current_user(
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> User:
    if credentials is None:
        raise AppError("AUTH_REQUIRED", "인증이 필요합니다.", 401)
    try:
        claims = decode_token(credentials.credentials, "access", request.app.state.settings)
    except jwt.PyJWTError as exc:
        raise AppError("INVALID_TOKEN", "유효하지 않은 인증 토큰입니다.", 401) from exc
    user = await db.get(User, claims.subject)
    if user is None:
        raise AppError("INVALID_TOKEN", "유효하지 않은 인증 토큰입니다.", 401)
    return user


DBSession = Annotated[AsyncSession, Depends(get_db)]
CurrentUser = Annotated[User, Depends(current_user)]
