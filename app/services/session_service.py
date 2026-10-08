from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.db.models.report import SessionReport
from app.db.models.session import PracticeSession, SessionStatus
from app.modules.speech.analysis import filler_counts

_NUMERIC_METRICS = {
    "duration_ms",
    "gaze_away_count",
    "average_syllables_per_minute",
    "pronunciation_clarity_score",
    "script_completion_ratio",
    "away_count",
    "away_duration_ms",
    "valid_duration_ms",
    "unknown_duration_ms",
    "coverage_ratio",
    "away_ratio",
    "syllable_count",
    "voiced_ms",
    "repeat_count",
    "warning_episode_count",
    "sample_count",
    "average_confidence",
    "completion_ratio",
    "average_absolute_pace_delta_ms",
    "syllables_per_minute",
    "elapsed_ms",
    "quality",
    "confidence",
    "face_detected",
    "calibrated",
    "away",
    "current_token_index",
    "current_sentence_index",
    "expected_token_index",
    "progress_ratio",
    "expected_progress_ratio",
    "pace_delta_ms",
    "match_score",
    "matched_start_token",
    "matched_end_token",
    "start_ms",
    "end_ms",
    "revision",
}
_ENUM_METRICS = {
    "status": {
        "observed",
        "observed_zero",
        "unavailable",
        "disabled",
        "estimated",
        "insufficient_signal",
    },
    "filler_status": {"observed", "observed_zero", "unavailable", "disabled"},
    "method": {"script_agreement", "unavailable"},
    "alignment_status": {"matched", "uncertain"},
    "pace_status": {"unknown", "on_time", "ahead", "behind"},
    "pace": {"unknown", "normal", "slow", "fast"},
    "attention_state": {"unknown", "baseline", "camera", "screen", "away"},
    "gaze_direction": {"unknown", "center", "left", "right", "up", "down"},
    "head_direction": {"unknown", "center", "left", "right", "up", "down"},
}


def _safe_fillers(value: Any) -> dict[str, int] | None:
    if not isinstance(value, dict):
        return None
    return {
        word: count
        for word, count in value.items()
        if isinstance(word, str)
        and isinstance(count, int)
        and count >= 0
        and filler_counts(word)[0].get(word)
    }


def _safe_metrics(metrics: dict[str, Any]) -> dict[str, Any]:
    # Positive allowlist: new provider fields cannot accidentally persist source text.
    safe: dict[str, Any] = {
        key: value
        for key, value in metrics.items()
        if key in _NUMERIC_METRICS and (value is None or isinstance(value, (int, float, bool)))
    }
    for key, values in _ENUM_METRICS.items():
        if isinstance(metrics.get(key), str) and metrics[key] in values:
            safe[key] = metrics[key]
    for key in ("filler_word_counts", "filler_counts"):
        if key in metrics:
            safe[key] = _safe_fillers(metrics[key])
    return safe


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
    if report_data.get("scoring_version") == "v2":
        session.duration_ms = max(
            0, int(report_data.get("summary", {}).get("duration_ms", fallback_duration_ms))
        )
    elif session.started_at:
        started_at = session.started_at
        if started_at.tzinfo is None:
            started_at = started_at.replace(tzinfo=timezone.utc)
        session.duration_ms = max(0, int((ended_at - started_at).total_seconds() * 1000))
    else:
        session.duration_ms = fallback_duration_ms
    persisted_report = {
        key: report_data.get(key)
        for key in (
            "overall_score",
            "gaze_score",
            "speech_rate_score",
            "filler_word_score",
            "pronunciation_clarity_score",
            "script_completion_ratio",
            "time_adherence_score",
            "gaze_away_count",
            "gaze_away_duration_ms",
            "average_syllables_per_minute",
        )
    }
    persisted_report.update(
        transcript=None,
        scoring_version="v2",
        incomplete=report_data.get("incomplete", True),
        filler_word_counts=_safe_fillers(report_data.get("filler_word_counts")),
        timeline=[
            {
                "timestamp_ms": item["timestamp_ms"],
                "source": item["source"],
                "level": item["level"],
                "metrics": _safe_metrics(item.get("metrics", {})),
            }
            for item in report_data.get("timeline", [])[-500:]
            if item.get("source") in {"gaze", "speech_rate", "pronunciation", "script_sync"}
            and isinstance(item.get("timestamp_ms"), int)
            and item.get("level") in {"info", "warning", "danger"}
        ],
    )
    for key in (
        "summary",
        "gaze_metrics",
        "speech_rate_metrics",
        "pronunciation_metrics",
        "script_sync_metrics",
    ):
        persisted_report[key] = _safe_metrics(report_data.get(key, {}))
    report = SessionReport(session_id=session.id, **persisted_report)
    db.add(report)
    session.status = SessionStatus.completed
    await db.commit()
    await db.refresh(report)
    return report
