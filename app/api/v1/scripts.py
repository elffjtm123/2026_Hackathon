from fastapi import APIRouter, Request

from app.api.deps import CurrentUser
from app.core.errors import AppError
from app.modules.script_sync.service import analyze_script, normalize_script
from app.schemas.script import ScriptAnalyzeRequest, ScriptAnalyzeResponse

router = APIRouter(tags=["scripts"])


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
