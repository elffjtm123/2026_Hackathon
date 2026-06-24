from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Query, Request
from sqlalchemy import select

from app.api.deps import CurrentUser, DBSession
from app.core.errors import AppError
from app.db.models.report import SessionReport
from app.db.models.session import PracticeSession, SessionStatus
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
    payload: SessionCreate, user: CurrentUser, db: DBSession
) -> PracticeSession:
    session = PracticeSession(
        user_id=user.id,
        type=payload.type,
        title=payload.title.strip(),
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
    session = await owned_session(db, session_id, user.id)
    if session.status not in {SessionStatus.created, SessionStatus.active}:
        raise AppError("INVALID_SESSION_STATE", "종료된 세션에는 연결할 수 없습니다.", 409)
    await activate_session(db, session)
    pipeline = await request.app.state.pipelines.get_or_create(session.id, session.settings)
    try:
        answer = await request.app.state.webrtc.create_answer(
            session.id, payload.sdp, payload.type, pipeline
        )
    except Exception as exc:
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
    report_data = await request.app.state.pipelines.stop(session.id)
    if report_data is None:
        from app.realtime.aggregator import FeedbackAggregator

        report_data = FeedbackAggregator().report()
    await request.app.state.webrtc.close_session(session.id)
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
