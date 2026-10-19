import asyncio
import ipaddress
import json
from collections.abc import AsyncIterator
from typing import Any

from anyio import CancelScope
from fastapi import APIRouter, Request
from starlette.responses import StreamingResponse

from app.api.deps import CurrentUser
from app.api.disconnect import disconnected_request
from app.core.errors import AppError
from app.modules.script_sync.service import analyze_script, normalize_script
from app.schemas.script import ScriptAnalyzeRequest, ScriptAnalyzeResponse, ScriptSummaryRequest

router = APIRouter(tags=["scripts"])


@router.post("/scripts/summarize")
async def script_summarize(payload: ScriptSummaryRequest, request: Request) -> Any:
    settings = request.app.state.settings
    if settings.ai_mode != "local":
        raise AppError(
            "LOCAL_MODE_REQUIRED", "메모리 분리 요약은 로컬 AI 모드에서만 지원합니다.", 409
        )
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
    if "application/x-ndjson" in request.headers.get("accept", ""):

        async def stream() -> AsyncIterator[str]:
            queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=512)

            def progress(data: dict[str, Any]) -> None:
                # Progress is advisory: drop frames instead of failing the request
                # when a slow reader has filled the queue.
                try:
                    queue.put_nowait({"event": "progress", "data": data})
                except asyncio.QueueFull:
                    pass

            async def produce() -> None:
                try:
                    result = await request.app.state.script_summarizer.summarize(
                        payload.script, on_progress=progress
                    )
                    # The terminal frame must never be dropped or the client hangs.
                    await queue.put({"event": "complete", "data": result})
                except AppError as exc:
                    await queue.put(
                        {"event": "error", "data": {"code": exc.code, "message": exc.message}}
                    )
                except Exception:
                    await queue.put(
                        {
                            "event": "error",
                            "data": {
                                "code": "SUMMARY_FAILED",
                                "message": "요약에 실패했습니다. 다시 시도하세요.",
                            },
                        }
                    )

            producer = asyncio.create_task(produce())
            try:
                while True:
                    event = await queue.get()
                    yield json.dumps(event, ensure_ascii=False) + "\n"
                    if event["event"] in {"complete", "error"}:
                        break
            finally:
                producer.cancel()
                with CancelScope(shield=True):
                    await asyncio.gather(producer, return_exceptions=True)

        return StreamingResponse(
            stream(),
            media_type="application/x-ndjson",
            headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
        )
    async with disconnected_request(
        request, "SUMMARY_CANCELLED", "연결이 종료되어 요약을 중단했습니다."
    ):
        return await request.app.state.script_summarizer.summarize(payload.script)


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
