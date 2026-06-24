from fastapi import APIRouter, Request, Response, status
from sqlalchemy import text

router = APIRouter(tags=["health"])


@router.get("/health/live")
async def live() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/health/ready")
async def ready(request: Request, response: Response) -> dict[str, object]:
    dependencies: dict[str, str] = {}
    try:
        async with request.app.state.database.sessions() as db:
            await db.execute(text("SELECT 1"))
        dependencies["database"] = "ok"
    except Exception:
        dependencies["database"] = "unavailable"
    try:
        redis_ok = await request.app.state.state_store.ping()
        dependencies["redis"] = "ok" if redis_ok else "unavailable"
    except Exception:
        dependencies["redis"] = "unavailable"
    is_ready = dependencies["database"] == "ok" and (
        dependencies["redis"] == "ok" or not request.app.state.settings.redis_required
    )
    if not is_ready:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return {"status": "ready" if is_ready else "not_ready", "dependencies": dependencies}
