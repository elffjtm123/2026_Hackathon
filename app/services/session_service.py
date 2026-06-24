from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.db.models.report import SessionReport
from app.db.models.session import PracticeSession, SessionStatus


async def owned_session(db: AsyncSession, session_id: UUID, user_id: UUID) -> PracticeSession:
    session = await db.scalar(
        select(PracticeSession).where(
            PracticeSession.id == session_id, PracticeSession.user_id == user_id
        )
    )
    if session is None:
        # Deliberately do not reveal whether another user owns this identifier.
        raise AppError("SESSION_NOT_FOUND", "세션을 찾을 수 없습니다.", 404)
    return session


async def list_owned_sessions(
    db: AsyncSession, user_id: UUID, page: int, page_size: int
) -> tuple[list[PracticeSession], int]:
    condition = PracticeSession.user_id == user_id
    total = await db.scalar(select(func.count()).select_from(PracticeSession).where(condition))
    sessions = list(
        (
            await db.scalars(
                select(PracticeSession)
                .where(condition)
                .order_by(PracticeSession.created_at.desc())
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
        ).all()
    )
    return sessions, int(total or 0)


async def activate_session(db: AsyncSession, session: PracticeSession) -> None:
    if session.status == SessionStatus.created:
        session.status = SessionStatus.active
        session.started_at = datetime.now(timezone.utc)
        await db.commit()


async def complete_session(
    db: AsyncSession,
    session: PracticeSession,
    report_data: dict[str, Any],
    fallback_duration_ms: int,
) -> SessionReport:
    if session.status == SessionStatus.completed:
        report = await db.scalar(
            select(SessionReport).where(SessionReport.session_id == session.id)
        )
        if report is None:
            raise AppError("REPORT_NOT_READY", "리포트가 아직 준비되지 않았습니다.", 409)
        return report
    if session.status not in {SessionStatus.created, SessionStatus.active}:
        raise AppError("INVALID_SESSION_STATE", "현재 상태에서는 세션을 종료할 수 없습니다.", 409)
    session.status = SessionStatus.processing
    ended_at = datetime.now(timezone.utc)
    session.ended_at = ended_at
    if session.started_at:
        started_at = session.started_at
        if started_at.tzinfo is None:
            started_at = started_at.replace(tzinfo=timezone.utc)
        session.duration_ms = max(0, int((ended_at - started_at).total_seconds() * 1000))
    else:
        session.duration_ms = fallback_duration_ms
    report = SessionReport(session_id=session.id, **report_data)
    db.add(report)
    session.status = SessionStatus.completed
    await db.commit()
    await db.refresh(report)
    return report
