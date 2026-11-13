import asyncio

from fastapi import APIRouter, Request

from app.api.local_only import local_request_verdict
from app.core.errors import AppError
from app.services.pretrained_pulse import PULSE_MODELS, pulse_contract, pulse_limit

router = APIRouter(prefix="/pulse", tags=["local-pretrained-pulse"])


def check_local(request: Request, write: bool = False) -> None:
    verdict = local_request_verdict(
        request,
        environments={"development", "test"},
        enabled=request.app.state.settings.pulse_enabled,
        origin="required" if write else "ignore",
    )
    if verdict == "disabled":
        raise AppError("NOT_FOUND", "맥박 실험 기능을 사용할 수 없습니다.", 404)
    if verdict == "not_local":
        raise AppError("LOCAL_ONLY", "허용된 로컬 발표 화면에서만 실행할 수 있습니다.", 403)


@router.get("/model")
async def model(request: Request, model_id: str = 'pure_efficientphys') -> dict:
    check_local(request)
    manager = request.app.state.pretrained_pulse
    contract = pulse_contract(model_id)
    return {
        "model": contract['name'],
        "model_id": model_id,
        "training_dataset": contract['dataset'],
        "available": manager.available(model_id),
        "models": [
            {"id": key, **value, "available": manager.available(key)}
            for key, value in PULSE_MODELS.items()
        ],
        "loaded": manager.session is not None,
        "busy": manager.busy,
        "runtime": "ONNX Runtime CPU",
        "nominal_fps": 30,
        "minimum_input_fps": 15,
    }


@router.post("/infer")
async def infer(request: Request, model_id: str = 'pure_efficientphys') -> dict:
    check_local(request, True)
    limit = pulse_limit(model_id)
    execution = request.app.state.model_execution
    if execution is not None and execution.owner == "summary":
        raise AppError("SUMMARY_BUSY", "대본 요약을 마친 뒤 발표를 시작해 주세요.", 409)
    if request.headers.get("content-type", "").split(";")[0] != "application/octet-stream":
        raise AppError("PULSE_CONTENT_TYPE", "올바른 영상 패킷이 필요합니다.", 415)
    manager = request.app.state.pretrained_pulse
    if manager.request_active:
        raise AppError("PULSE_BUSY", "다른 맥박 입력을 처리 중입니다.", 409)
    manager.request_active = True

    async def read_body() -> bytes:
        data = bytearray()
        async for chunk in request.stream():
            if len(data) + len(chunk) > limit:
                raise AppError("PULSE_PACKET_TOO_LARGE", "맥박 입력 크기를 초과했습니다.", 413)
            data.extend(chunk)
        return bytes(data)

    try:
        try:
            payload = await asyncio.wait_for(read_body(), 10)
        except asyncio.TimeoutError as exc:
            raise AppError(
                "PULSE_UPLOAD_TIMEOUT", "맥박 입력 수신 시간이 초과되었습니다.", 408
            ) from exc
        return await manager.infer(payload, model_id)
    finally:
        manager.request_active = False
