from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Request
from sqlalchemy import select

from app.api.deps import CurrentUser, DBSession
from app.core.errors import AppError
from app.db.models.session import PracticeSession
from app.db.models.style_transfer import StyleTransferJob
from app.modules.script_sync.service import analyze_script, normalize_script
from app.modules.style_transfer.service import PRESETS, MockStyleTransferProvider, normalize_weights
from app.schemas.script import (
    ScriptAnalyzeRequest,
    ScriptAnalyzeResponse,
    StylePresetResponse,
    StyleTransferPreviewResponse,
    StyleTransferRequest,
    StyleTransferResponse,
)

router = APIRouter(tags=["scripts"])


def require_style_transfer_enabled(session: PracticeSession) -> None:
    if not session.settings.get("style_transfer_enabled", True):
        raise AppError(
            "FEATURE_DISABLED",
            "이 세션에서는 대본 스타일 전이 기능이 꺼져 있습니다.",
            409,
            {"feature": "style_transfer"},
        )


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


@router.get("/styles/presets", response_model=list[StylePresetResponse])
async def style_presets(user: CurrentUser) -> list[dict[str, object]]:
    del user
    return list(PRESETS.values())


@router.post("/scripts/style-transfer/demo", response_model=StyleTransferPreviewResponse)
async def demo_style_transfer(
    payload: StyleTransferRequest, request: Request
) -> StyleTransferPreviewResponse:
    if request.app.state.settings.app_env == "production":
        raise AppError("UNAUTHORIZED", "운영 환경에서는 데모 변환을 사용할 수 없습니다.", 403)
    script = validate_script(payload.script, payload.time_limit_seconds, request)
    unknown = set(payload.style_vector) - set(PRESETS)
    if unknown:
        raise AppError("INVALID_STYLE_PRESET", "지원하지 않는 스타일 preset이 있습니다.", 422)
    vector = normalize_weights(payload.style_vector)
    result = await MockStyleTransferProvider().transform(
        script, payload.time_limit_seconds, vector, payload.intensity
    )
    if not result["safety"]["passed"]:
        raise AppError(
            "STYLE_SAFETY_REJECTED",
            "안전 정책을 통과하지 못해 스타일 변환을 거부했습니다.",
            422,
            result["safety"],
        )
    return StyleTransferPreviewResponse(
        transformed_script=result["script"],
        estimated_duration_seconds=result["estimated_duration_seconds"],
        change_summary=result["change_summary"],
        warnings=result["warnings"],
        safety=result["safety"],
        style_vector=vector,
        provider="mock",
    )


def job_response(job: StyleTransferJob) -> StyleTransferResponse:
    return StyleTransferResponse(
        job_id=job.id,
        status=job.status,
        original_script=job.source_script,
        transformed_script=job.result_script,
        estimated_duration_seconds=job.estimated_duration_seconds,
        change_summary=job.change_summary,
        warnings=job.warnings,
        safety=job.safety_result,
        style_vector=job.style_vector,
        provider=job.provider,
        created_at=job.created_at,
    )


@router.post("/scripts/style-transfer", response_model=StyleTransferResponse, status_code=201)
async def style_transfer(
    payload: StyleTransferRequest, request: Request, user: CurrentUser, db: DBSession
) -> StyleTransferResponse:
    script = validate_script(payload.script, payload.time_limit_seconds, request)
    unknown = set(payload.style_vector) - set(PRESETS)
    if unknown:
        raise AppError("INVALID_STYLE_PRESET", "지원하지 않는 스타일 preset이 있습니다.", 422)
    if payload.session_id is not None:
        session = await db.scalar(
            select(PracticeSession).where(
                PracticeSession.id == payload.session_id, PracticeSession.user_id == user.id
            )
        )
        if session is None:
            raise AppError("SESSION_NOT_FOUND", "세션을 찾을 수 없습니다.", 404)
        require_style_transfer_enabled(session)
    vector = normalize_weights(payload.style_vector)
    result = await MockStyleTransferProvider().transform(
        script, payload.time_limit_seconds, vector, payload.intensity
    )
    job = StyleTransferJob(
        user_id=user.id,
        session_id=payload.session_id,
        status="completed" if result["safety"]["passed"] else "rejected",
        source_script=script,
        result_script=result["script"] if result["safety"]["passed"] else None,
        style_vector=vector,
        intensity=payload.intensity,
        estimated_duration_seconds=result["estimated_duration_seconds"],
        change_summary=result["change_summary"],
        warnings=result["warnings"],
        safety_result=result["safety"],
        provider="mock",
        provider_model="rules-v1",
        completed_at=datetime.now(timezone.utc),
    )
    db.add(job)
    await db.commit()
    await db.refresh(job)
    if not result["safety"]["passed"]:
        raise AppError(
            "STYLE_SAFETY_REJECTED",
            "안전 정책을 통과하지 못해 스타일 변환을 거부했습니다.",
            422,
            result["safety"],
        )
    return job_response(job)


@router.get("/scripts/style-transfer/{job_id}", response_model=StyleTransferResponse)
async def get_style_transfer(
    job_id: UUID, user: CurrentUser, db: DBSession
) -> StyleTransferResponse:
    job = await db.scalar(
        select(StyleTransferJob).where(
            StyleTransferJob.id == job_id, StyleTransferJob.user_id == user.id
        )
    )
    if job is None:
        raise AppError("STYLE_JOB_NOT_FOUND", "스타일 변환 작업을 찾을 수 없습니다.", 404)
    return job_response(job)


@router.post("/scripts/style-transfer/{job_id}/apply", response_model=StyleTransferResponse)
async def apply_style_transfer(
    job_id: UUID, user: CurrentUser, db: DBSession
) -> StyleTransferResponse:
    job = await db.scalar(
        select(StyleTransferJob).where(
            StyleTransferJob.id == job_id, StyleTransferJob.user_id == user.id
        )
    )
    if job is None:
        raise AppError("STYLE_JOB_NOT_FOUND", "스타일 변환 작업을 찾을 수 없습니다.", 404)
    if job.status != "completed" or not job.result_script:
        raise AppError("STYLE_TRANSFER_FAILED", "적용할 변환 결과가 없습니다.", 409)
    if job.session_id is None:
        raise AppError("SESSION_REQUIRED", "적용할 세션이 지정되지 않았습니다.", 409)
    session = await db.scalar(
        select(PracticeSession).where(
            PracticeSession.id == job.session_id, PracticeSession.user_id == user.id
        )
    )
    if session is None:
        raise AppError("SESSION_NOT_FOUND", "세션을 찾을 수 없습니다.", 404)
    require_style_transfer_enabled(session)
    session.active_script = job.result_script
    plan = analyze_script(job.result_script, session.time_limit_seconds or 300)
    session.script_syllable_count = plan.syllable_count
    session.target_syllables_per_minute = plan.target_syllables_per_minute
    job.status = "applied"
    await db.commit()
    await db.refresh(job)
    return job_response(job)
