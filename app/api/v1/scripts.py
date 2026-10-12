import asyncio
import ipaddress
from typing import Any

from fastapi import APIRouter, Request

from app.api.deps import CurrentUser
from app.core.errors import AppError
from app.modules.script_sync.service import analyze_script, normalize_script
from app.schemas.script import ScriptAnalyzeRequest, ScriptAnalyzeResponse, ScriptSummaryRequest

router = APIRouter(tags=["scripts"])


@router.post("/scripts/summarize")
async def script_summarize(payload: ScriptSummaryRequest, request: Request) -> dict[str, Any]:
    settings = request.app.state.settings
    try:
        local = request.client is not None and ipaddress.ip_address(request.client.host).is_loopback
    except ValueError:
        local = False
    if (
        settings.app_env != "development"
        or not local
        or request.headers.get("origin") not in settings.cors_origins
    ):
        raise AppError("DEVELOPMENT_ONLY", "로컬 개발 화면에서만 요약할 수 있습니다.", 403)
    if request.app.state.live_sessions or any(
        p.running for p in request.app.state.pipelines.pipelines.values()
    ):
        raise AppError("PRACTICE_ACTIVE", "발표·면접 세션을 종료한 뒤 요약해 주세요.", 409)
    owner = asyncio.current_task()
    disconnected = False

    async def cancel_on_disconnect() -> None:
        nonlocal disconnected
        while True:
            # The body is consumed; block on receive instead of cancelling middleware polling.
            if (await request.receive())["type"] == "http.disconnect":
                disconnected = True
                if owner is not None:
                    owner.cancel()
                return

    watcher = asyncio.create_task(cancel_on_disconnect())
    try:
        return await request.app.state.script_summarizer.summarize(payload.script)
    except asyncio.CancelledError:
        if disconnected:
            raise AppError(
                "SUMMARY_CANCELLED", "연결이 종료되어 요약을 중단했습니다.", 499
            ) from None
        raise
    finally:
        watcher.cancel()
        await asyncio.gather(watcher, return_exceptions=True)


def validate_script(script: str, time_limit_seconds: int, request: Request) -> str:
    normalized = normalize_script(script)
    settings = request.app.state.settings
    if not normalized:
        raise AppError("SCRIPT_REQUIRED", "대본을 입력해 주세요.", 422)
    if len(normalized) > settings.max_script_chars:
        raise AppError("SCRIPT_TOO_LONG", "대본이 허용된 최대 길이를 초과했습니다.", 422)
    if not settings.min_time_limit_seconds <= time_limit_seconds <= settings.max_time_limit_seconds:
        raise AppError("INVALID_TIME_LIMIT", "제한시간이 허용 범위를 벗어났습니다.", 422)
    return normalized


@router.post("/scripts/analyze", response_model=ScriptAnalyzeResponse)
async def script_analyze(
    payload: ScriptAnalyzeRequest, request: Request, user: CurrentUser
) -> dict[str, object]:
    del user
    script = validate_script(payload.script, payload.time_limit_seconds, request)
    return analyze_script(script, payload.time_limit_seconds).as_dict()
