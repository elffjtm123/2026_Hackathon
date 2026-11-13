import json
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile

from app.ai.experimental_stt import MODEL_IDS
from app.core.errors import AppError
from app.services.stt_experiments import MAX_AUDIO_BYTES, read_wav


def local_development_only(request: Request) -> None:
    settings = request.app.state.settings
    if settings.app_env == "production" or not settings.stt_experiments_enabled:
        raise AppError("NOT_FOUND", "실험 기능을 사용할 수 없습니다.", 404)
    host = request.client.host if request.client else ""
    if settings.app_env != "test" and host not in {"127.0.0.1", "::1"}:
        raise AppError("LOCAL_ONLY", "비교 실험은 로컬 컴퓨터에서만 실행할 수 있습니다.", 403)


router = APIRouter(
    prefix="/stt-experiments",
    tags=["local-stt-experiments"],
    dependencies=[Depends(local_development_only)],
)


def service_session_active(request: Request) -> bool:
    state = request.app.state
    return bool(
        state.experiment_session_count
        or state.live_speech.busy
        or (state.model_execution is not None and state.model_execution.owner is not None)
        or state.pipelines.pipelines
        or any(state.webrtc.connections.values())
    )


@router.get("/models")
async def models(request: Request) -> dict:
    manager = request.app.state.stt_experiments
    return {
        "models": manager.models(),
        "busy": manager.busy or service_session_active(request),
        "max_audio_seconds": 60,
    }


@router.post("/jobs", status_code=202)
async def start_job(
    request: Request,
    audio: Annotated[UploadFile, File()],
    models: Annotated[str, Form()],
    reference: Annotated[str, Form(max_length=10000)] = "",
    chunk_seconds: Annotated[int, Form(ge=2, le=4)] = 2,
    warmup: Annotated[bool, Form()] = True,
) -> dict:
    manager = request.app.state.stt_experiments
    if manager.busy or service_session_active(request):
        raise AppError("EXPERIMENT_BUSY", "연습 세션이나 다른 비교 실험을 먼저 종료해 주세요.", 409)
    try:
        ids = json.loads(models)
        if (
            not isinstance(ids, list)
            or not 1 <= len(ids) <= 5
            or any(not isinstance(i, str) or i not in MODEL_IDS for i in ids)
            or len(set(ids)) != len(ids)
        ):
            raise ValueError("비교 모델을 1~5개 선택하세요. 중복 선택은 허용되지 않습니다.")
        payload = await audio.read(MAX_AUDIO_BYTES + 1)
        if len(payload) > MAX_AUDIO_BYTES:
            raise AppError("AUDIO_TOO_LARGE", "60초 이하 WAV 파일을 사용하세요.", 413)
        pcm = read_wav(payload)
    except (ValueError, TypeError) as exc:
        raise AppError("INVALID_EXPERIMENT", str(exc), 400) from exc
    finally:
        await audio.close()
    # Upload reading yielded control; recheck before reserving the model worker.
    if manager.busy or service_session_active(request):
        raise AppError("EXPERIMENT_BUSY", "다른 세션 또는 실험이 실행 중입니다.", 409)
    return manager.start(pcm, ids, reference, chunk_seconds, True, warmup)


@router.get("/jobs/{job_id}")
async def get_job(request: Request, job_id: str) -> dict:
    job = request.app.state.stt_experiments.jobs.get(job_id)
    if job is None:
        raise AppError("JOB_NOT_FOUND", "실험이 없거나 서버 재시작으로 만료되었습니다.", 404)
    return job


@router.post("/jobs/{job_id}/cancel")
async def cancel_job(request: Request, job_id: str) -> dict:
    job = await get_job(request, job_id)
    if job["state"] == "running":
        job["cancel_requested"] = True
    return job
