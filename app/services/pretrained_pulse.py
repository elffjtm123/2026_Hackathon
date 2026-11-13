"""Bounded, stateless EfficientPhys inference; never stores face videos or scores."""

from __future__ import annotations
import asyncio
import hashlib
import json
import struct
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    import numpy as np

from app.core.errors import AppError
from app.ai.model_execution import finish

MAX_PULSE_BYTES = 2 * 1024 * 1024
FRAME_BYTES = 72 * 72 * 3
PULSE_MODELS = {
    'ma_ubfc_tscan': {'name':'TS-CAN', 'dataset':'Motion-augmented UBFC-rPPG', 'size':72, 'duration_ms':3000, 'outputs':90},
    'pure_efficientphys': {'name':'EfficientPhys', 'dataset':'PURE', 'size':72, 'duration_ms':3000, 'outputs':90},
    'ubfc_efficientphys': {'name':'EfficientPhys', 'dataset':'UBFC-rPPG', 'size':72, 'duration_ms':3000, 'outputs':90},
    'ubfc_tscan': {'name':'TS-CAN', 'dataset':'UBFC-rPPG', 'size':72, 'duration_ms':3000, 'outputs':90},
    'ubfc_physformer': {'name':'PhysFormer', 'dataset':'UBFC-rPPG', 'size':128, 'duration_ms':160000/30, 'outputs':160},
}

def pulse_contract(model_id: str) -> dict:
    if model_id not in PULSE_MODELS:
        raise AppError('PULSE_MODEL_UNKNOWN', '지원하지 않는 맥박 모델입니다.', 422)
    return PULSE_MODELS[model_id]

def pulse_limit(model_id: str) -> int:
    return 10 * 1024 * 1024 if pulse_contract(model_id)['size'] == 128 else MAX_PULSE_BYTES


def read_pulse_packet(payload: bytes, model_id: str = 'pure_efficientphys') -> tuple[np.ndarray, np.ndarray]:
    import numpy as np

    contract = pulse_contract(model_id)
    size = contract['size']
    frame_bytes = size * size * 3
    magic = b'EP02' if size == 128 else b'EP01'
    if len(payload) < 8 or len(payload) > pulse_limit(model_id) or payload[:4] != magic:
        raise ValueError("INVALID_PULSE_PACKET")
    count, reserved = struct.unpack_from("<HH", payload, 4)
    if not 46 <= count <= (181 if size == 128 else 121) or reserved or len(payload) != 8 + count * (8 + frame_bytes):
        raise ValueError("INVALID_PULSE_FRAME_COUNT")
    times = np.frombuffer(payload, dtype="<f8", count=count, offset=8).copy()
    gaps = np.diff(times)
    duration = times[-1] - times[0]
    if (
        not np.isfinite(times).all()
        or times[0] < 0
        or not contract['duration_ms'] <= duration <= contract['duration_ms'] + 250
        or np.any(gaps <= 0)
        or np.any(gaps > 250)
        or (count - 1) * 1000 / duration < 15
    ):
        raise ValueError("PULSE_CAPTURE_TIMING_UNRELIABLE")
    frames = np.frombuffer(payload, dtype=np.uint8, offset=8 + count * 8).reshape(count, size, size, 3)
    return times, frames


def prepare_pulse_tensor(times: np.ndarray, frames: np.ndarray, model_id: str = 'pure_efficientphys') -> np.ndarray:
    import numpy as np

    # The official PURE configuration uses 30fps, 72x72 RGB, Standardized.
    # Actual timestamps are resampled; interpolation is not extra captured data.
    count = pulse_contract(model_id)['outputs']
    target = times[0] + np.arange(count + 1) * (1000 / 30)
    right = np.clip(np.searchsorted(times, target), 1, len(times) - 1)
    left = right - 1
    alpha = ((target - times[left]) / (times[right] - times[left])).astype(np.float32)
    x = frames[left].astype(np.float32) * (1 - alpha[:, None, None, None])
    x += frames[right].astype(np.float32) * alpha[:, None, None, None]
    scale = float(x.std())
    if not np.isfinite(scale) or scale < 1:
        raise ValueError("PULSE_IMAGE_SIGNAL_TOO_WEAK")
    standardized = (x - float(x.mean())) / scale
    if model_id in ('ubfc_tscan', 'ma_ubfc_tscan', 'ubfc_physformer'):
        motion = (x[1:] - x[:-1]) / (x[1:] + x[:-1] + 1e-7)
        motion = motion / max(float(motion.std()), 1e-7)
        if model_id == 'ubfc_physformer':
            return np.ascontiguousarray(motion.transpose(3,0,1,2)[None], dtype=np.float32)
        x = np.concatenate((motion, standardized[:-1]), axis=3)
    else:
        x = standardized
    return np.ascontiguousarray(x.transpose(0, 3, 1, 2), dtype=np.float32)


class PretrainedPulse:
    def __init__(self, directory: str) -> None:
        self.directory = Path(directory)
        self.session: Any = None  # onnxruntime.InferenceSession once loaded
        self.busy = False
        self.closed = False
        self.request_active = False
        self.last_used = 0.0
        self.loaded_model_id: str | None = None

    def paths(self, model_id: str):
        pulse_contract(model_id)
        if model_id == 'pure_efficientphys':
            return self.directory / 'EfficientPhys-PURE-91.onnx', self.directory / 'manifest.json'
        return self.directory / 'ubfc' / (model_id + '.onnx'), self.directory / 'ubfc' / (model_id + '.json')

    def available(self, model_id: str = 'pure_efficientphys') -> bool:
        path, manifest = self.paths(model_id)
        return path.is_file() and manifest.is_file()

    def _run(self, times: np.ndarray, frames: np.ndarray, model_id: str = 'pure_efficientphys') -> dict:
        import numpy as np
        import onnxruntime as ort

        contract = pulse_contract(model_id)
        path, manifest_path = self.paths(model_id)
        if self.session is None or self.loaded_model_id != model_id:
            self.session = None
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            expected = manifest['files'][path.name]['sha256'] if model_id == 'pure_efficientphys' else manifest['sha256']
            if hashlib.sha256(path.read_bytes()).hexdigest() != expected:
                raise ValueError("PULSE_MODEL_CHECKSUM_MISMATCH")
            options = ort.SessionOptions()
            options.intra_op_num_threads = 2
            options.inter_op_num_threads = 1
            self.session = ort.InferenceSession(
                str(path), sess_options=options, providers=["CPUExecutionProvider"]
            )
            self.loaded_model_id = model_id
        tensor = prepare_pulse_tensor(times, frames, model_id)
        started = time.perf_counter()
        result = self.session.run(None, {"frames": tensor})[0].reshape(-1)
        elapsed = (time.perf_counter() - started) * 1000
        if result.shape != (contract['outputs'],) or not np.isfinite(result).all():
            raise ValueError("PULSE_MODEL_INVALID_OUTPUT")
        return {
            "model": contract['name'],
            "model_id": model_id,
            "training_dataset": contract['dataset'],
            "runtime": "ONNX Runtime CPU",
            "start_ms": float(times[0] + 1000 / 30),
            "sample_rate": 30,
            "input_fps": (len(times) - 1) * 1000 / float(times[-1] - times[0]),
            "inference_ms": round(elapsed, 2),
            "values": result.tolist(),
        }

    async def infer(self, payload: bytes, model_id: str = 'pure_efficientphys') -> dict:
        if self.closed:
            raise AppError("PULSE_UNAVAILABLE", "맥박 모델이 종료되었습니다.", 503)
        if self.busy:
            raise AppError("PULSE_BUSY", "다른 맥박 입력을 처리 중입니다.", 409)
        # A malformed packet is the client's error whatever the model state, so validate first.
        try:
            times, frames = read_pulse_packet(payload, model_id)
        except ValueError as exc:
            raise AppError(str(exc), "유효 영상과 촬영 시각을 확인해 주세요.", 422) from exc
        if not (self.available() if model_id == 'pure_efficientphys' else self.available(model_id)):
            raise AppError(
                "PULSE_MODEL_MISSING", "선택한 맥박 모델 파일이 준비되지 않았습니다.", 503
            )
        self.busy = True
        task = asyncio.create_task(asyncio.to_thread(self._run, times, frames, model_id))
        try:
            return await finish(task)
        except Exception as exc:
            raise AppError(
                "PULSE_INFERENCE_FAILED",
                "EfficientPhys 추론에 실패했습니다. 모델 파일과 실행 환경을 확인해 주세요.",
                503,
            ) from exc
        finally:
            self.busy = False
            self.last_used = time.monotonic()

    async def idle_cleanup(self) -> None:
        while not self.closed:
            await asyncio.sleep(10)
            if not self.busy and time.monotonic() - self.last_used > 30:
                self.session = None

    async def close(self) -> None:
        self.closed = True
        while self.busy:
            await asyncio.sleep(0.05)
        self.session = None
