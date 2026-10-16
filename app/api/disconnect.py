"""Cancel long HTTP work on disconnect, after FastAPI has consumed the request body."""

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import Request

from app.core.errors import AppError


@asynccontextmanager
async def disconnected_request(request: Request, code: str, message: str) -> AsyncIterator[None]:
    owner = asyncio.current_task()
    disconnected = False

    async def watch() -> None:
        nonlocal disconnected
        while True:
            if (await request.receive())["type"] == "http.disconnect":
                disconnected = True
                if owner is not None:
                    owner.cancel()
                return

    watcher = asyncio.create_task(watch())
    try:
        yield
    except asyncio.CancelledError:
        if disconnected:
            raise AppError(code, message, 499) from None
        raise
    finally:
        watcher.cancel()
        await asyncio.gather(watcher, return_exceptions=True)
