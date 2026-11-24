"""Shared preconditions of the local-only, model-using HTTP endpoints (summary, interview).

Each endpoint passes its own Korean messages; the error codes and statuses are fixed here.
"""

from dataclasses import dataclass

from fastapi import Request

from app.api.local_only import local_request_verdict
from app.core.errors import AppError


@dataclass(frozen=True)
class GuardMessages:
    local_mode_required: str
    development_only: str
    practice_active: str
    summary_busy: str = "요약 처리와 모델 정리가 끝난 뒤 다시 시도하세요."
    interview_busy: str = "진행 중인 면접 준비가 끝난 뒤 다시 시도하세요."


def require_local_idle_request(request: Request, messages: GuardMessages) -> None:
    """Local AI mode, allowed browser Origin on loopback, and no live practice session."""
    if request.app.state.settings.ai_mode != "local":
        raise AppError("LOCAL_MODE_REQUIRED", messages.local_mode_required, 409)
    if local_request_verdict(request, origin="required") != "allowed":
        raise AppError("DEVELOPMENT_ONLY", messages.development_only, 403)
    if request.app.state.live_sessions or any(
        p.running for p in request.app.state.pipelines.pipelines.values()
    ):
        raise AppError("PRACTICE_ACTIVE", messages.practice_active, 409)


def require_no_offline_job(request: Request, messages: GuardMessages) -> None:
    """For endpoints that do not reserve the models themselves but must not overlap an offline
    job (summary or interview planning/evaluation) that owns them."""
    execution = request.app.state.model_execution
    owner = None if execution is None else execution.owner
    if isinstance(owner, str):
        if owner == "summary":
            raise AppError("SUMMARY_BUSY", messages.summary_busy, 409)
        raise AppError("INTERVIEW_BUSY", messages.interview_busy, 409)
