from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Query, Request
from sqlalchemy import select

from app.api.deps import CurrentUser, DBSession
from app.api.disconnect import disconnected_request
from app.api.v1.scripts import validate_script
from app.core.errors import AppError
from app.db.models.report import SessionReport
from app.db.models.session import PracticeSession, SessionStatus
from app.modules.script_sync.service import analyze_script
from app.schemas.session import (
    ReportResponse,
    SessionCreate,
    SessionListResponse,
    SessionResponse,
    WebRTCAnswer,
    WebRTCOffer,
)
from app.services.session_service import (
    activate_session,
    complete_session,
    list_owned_sessions,
    owned_session,
)

router = APIRouter(prefix="/sessions", tags=["sessions"])


@router.post("", response_model=SessionResponse, status_code=201)
async def create_session(
    payload: SessionCreate, request: Request, user: CurrentUser, db: DBSession
) -> PracticeSession:
    script = None
    plan = None
    if payload.script is not None or payload.time_limit_seconds is not None:
        if payload.script is None:
            raise AppError("SCRIPT_REQUIRED", "대본을 입력해 주세요.", 422)
        if payload.time_limit_seconds is None:
            raise AppError("INVALID_TIME_LIMIT", "제한시간을 입력해 주세요.", 422)
        script = validate_script(payload.script, payload.time_limit_seconds, request)
        plan = analyze_script(script, payload.time_limit_seconds)
        if plan.target_syllables_per_minute > 600:
            raise AppError(
                "UNREALISTIC_TARGET_PACE",
                "대본 길이와 제한시간으로 계산한 목표 속도가 비현실적입니다.",
                422,
                {"target_syllables_per_minute": plan.target_syllables_per_minute},
            )
    session = PracticeSession(
        user_id=user.id,
        type=payload.type,
        title=payload.title.strip(),
        original_script=script,
        active_script=script,
        time_limit_seconds=payload.time_limit_seconds,
        script_syllable_count=plan.syllable_count if plan else None,
        target_syllables_per_minute=plan.target_syllables_per_minute if plan else None,
        settings=payload.settings.model_dump(),
    )
    db.add(session)
    await db.commit()
    await db.refresh(session)
    return session


@router.get("", response_model=SessionListResponse)
async def list_sessions(
    user: CurrentUser,
    db: DBSession,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
) -> SessionListResponse:
    sessions, total = await list_owned_sessions(db, user.id, page, page_size)
    return SessionListResponse(items=sessions, total=total, page=page, page_size=page_size)


@router.get("/{session_id}", response_model=SessionResponse)
async def get_session(session_id: UUID, user: CurrentUser, db: DBSession) -> PracticeSession:
    return await owned_session(db, session_id, user.id)


@router.post("/{session_id}/webrtc/offer", response_model=WebRTCAnswer)
async def webrtc_offer(
    session_id: UUID,
    payload: WebRTCOffer,
    request: Request,
    user: CurrentUser,
    db: DBSession,
) -> WebRTCAnswer:
    async with disconnected_request(
        request, "WEBRTC_CANCELLED", "연결이 종료되어 모델 준비를 중단했습니다."
    ):
        return await _negotiate_webrtc(session_id, payload, request, user, db)


async def _negotiate_webrtc(
    session_id: UUID,
    payload: WebRTCOffer,
    request: Request,
    user: CurrentUser,
    db: DBSession,
) -> WebRTCAnswer:
    session = await owned_session(db, session_id, user.id)
    if session.status not in {SessionStatus.created, SessionStatus.active}:
        raise AppError("INVALID_SESSION_STATE", "종료된 세션에는 연결할 수 없습니다.", 409)
    await activate_session(db, session)
    previous_pipeline = request.app.state.pipelines.get(session.id)
    try:
        pipeline = await request.app.state.pipelines.get_or_create(
            session.id,
            {
                **session.settings,
                "script": session.active_script,
                "time_limit_seconds": session.time_limit_seconds,
            },
        )
    except ValueError as exc:
        if str(exc) == "SUMMARY_BUSY":
            raise AppError("SUMMARY_BUSY", "요약 모델 정리가 끝난 뒤 시작해 주세요.", 409) from exc
        raise AppError(
            "MODEL_UNAVAILABLE_OR_BUSY", "필요한 모델이 준비되지 않았거나 처리 중입니다.", 503
        ) from exc
    try:
        answer = await request.app.state.webrtc.create_answer(
            session.id, payload.sdp, payload.type, pipeline
        )
    except BaseException as exc:
        if previous_pipeline is None:
            from anyio import CancelScope

            with CancelScope(shield=True):
                registry = request.app.state.pipelines
                async with registry._lock:
                    if (
                        registry.get(session.id) is pipeline
                        and not pipeline.subscribers
                        and not request.app.state.webrtc.connections.get(session.id)
                    ):
                        try:
                            await pipeline.stop()
                        finally:
                            registry.pipelines.pop(session.id, None)
        if not isinstance(exc, Exception):
            raise
        if isinstance(exc, AppError):
            # Capacity and policy rejections keep their own status code.
            raise
        raise AppError(
            "WEBRTC_NEGOTIATION_FAILED", "WebRTC 연결 협상에 실패했습니다.", 400
        ) from exc
    return WebRTCAnswer(sdp=answer.sdp)


@router.post("/{session_id}/complete", response_model=ReportResponse)
async def finish_session(
    session_id: UUID, request: Request, user: CurrentUser, db: DBSession
) -> SessionReport:
    session = await owned_session(db, session_id, user.id)
    pipeline = request.app.state.pipelines.get(session.id)
    fallback_duration = pipeline.elapsed_ms() if pipeline else 0
    await request.app.state.webrtc.close_session(session.id)
    report_data = await request.app.state.pipelines.stop(session.id)
    if report_data is None:
        from app.realtime.aggregator import FeedbackAggregator

        report_data = {**FeedbackAggregator().report(settings=session.settings), "incomplete": True}
    return await complete_session(db, session, report_data, fallback_duration)


@router.delete("/{session_id}", status_code=204)
async def delete_session(
    session_id: UUID, request: Request, user: CurrentUser, db: DBSession
) -> None:
    session = await owned_session(db, session_id, user.id)
    await request.app.state.pipelines.stop(session.id)
    await request.app.state.webrtc.close_session(session.id)
    await db.delete(session)
    await db.commit()


@router.get("/{session_id}/report", response_model=ReportResponse)
async def get_report(session_id: UUID, user: CurrentUser, db: DBSession) -> SessionReport:
    session = await owned_session(db, session_id, user.id)
    report = await db.scalar(select(SessionReport).where(SessionReport.session_id == session.id))
    if report is None:
        raise AppError("REPORT_NOT_READY", "리포트가 아직 준비되지 않았습니다.", 409)
    return report
