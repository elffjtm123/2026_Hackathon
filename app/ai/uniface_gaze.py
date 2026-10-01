import math
import time
from collections.abc import Callable
from dataclasses import asdict
from typing import Any
from uuid import UUID

from app.ai.base import AIResult, InferenceGate, MediaPayload
from app.modules.gaze.service import GazeObservation


class UniFaceGazeAdapter:
    def __init__(
        self,
        detector: Any = None,
        estimator: Any = None,
        decoder: Callable[[bytes], Any] | None = None,
        face_observer: Any = None,
        asset_path: str = ".models/face_landmarker.task",
    ) -> None:
        import numpy as np

        if decoder is None:
            import cv2

            def decoder(payload: bytes) -> Any:
                return cv2.imdecode(np.frombuffer(payload, dtype=np.uint8), cv2.IMREAD_COLOR)

        if estimator is None:
            import onnxruntime as ort
            from uniface.gaze import MobileGaze

            providers = [
                p
                for p in ("CoreMLExecutionProvider", "CPUExecutionProvider")
                if p in ort.get_available_providers()
            ]
            estimator = MobileGaze(providers=providers)
        if face_observer is None and detector is None:
            from app.ai.face_observation import FaceObserver

            face_observer = FaceObserver(asset_path)
        self.detector, self.estimator, self.decoder, self.observer = (
            detector,
            estimator,
            decoder,
            face_observer,
        )
        self.gate = InferenceGate()
        self.session_id: UUID | None = None

    async def infer(self, media: MediaPayload) -> AIResult:
        return await self.gate.run_once(lambda: self._infer_sync(media))

    def close(self) -> None:
        if self.observer is not None:
            self.gate.executor.submit(self.observer.close)
        self.gate.close()

    def _infer_sync(self, media: MediaPayload) -> AIResult:
        started = time.perf_counter()
        empty_pose: dict[str, float | None] = {"yaw": None, "pitch": None, "roll": None}
        observation = GazeObservation(
            False,
            empty_pose,
            {"yaw": None, "pitch": None},
            None,
            ["invalid_frame"],
            media.timestamp_ms,
        )
        frame = self.decoder(media.payload)
        if frame is not None and getattr(frame, "size", False):
            if self.observer is not None:
                if self.session_id != media.session_id:
                    self.observer.reset()
                self.session_id = media.session_id
                observation = self.observer.observe_face(frame, media.timestamp_ms)
            else:
                # ponytail: injected detector is diagnostic-only; no head pose measurement.
                faces = self.detector.detect(frame)
                if len(faces) == 1:
                    h, w = frame.shape[:2]
                    x1, y1, x2, y2 = (int(v) for v in faces[0].bbox[:4])
                    observation = GazeObservation(
                        True,
                        empty_pose,
                        {"yaw": None, "pitch": None},
                        float(faces[0].confidence),
                        ["pose_unavailable"],
                        media.timestamp_ms,
                        (max(0, x1), max(0, y1), min(w, x2), min(h, y2)),
                    )
                else:
                    observation = GazeObservation(
                        False,
                        empty_pose,
                        {"yaw": None, "pitch": None},
                        None,
                        ["no_face" if not faces else "multiple_faces"],
                        media.timestamp_ms,
                    )
            if observation.bbox is not None and not (
                set(observation.quality_flags) - {"pose_unavailable"}
            ):
                x1, y1, x2, y2 = observation.bbox
                crop = frame[y1:y2, x1:x2]
                if crop.size:
                    estimate = self.estimator.estimate(crop)
                    yaw, pitch = (
                        math.degrees(float(estimate.yaw)),
                        math.degrees(float(estimate.pitch)),
                    )
                    if math.isfinite(yaw) and math.isfinite(pitch):
                        observation.gaze_angles.update(yaw=yaw, pitch=pitch)
                    else:
                        observation.quality_flags.append("gaze_unavailable")
        metrics = {
            **asdict(observation),
            "quality": 1.0 if not observation.quality_flags else 0.0,
            "gaze_direction": "unknown",
            "attention_state": "unknown",
            "calibrated": False,
            "away": False,
        }
        return AIResult(
            "gaze",
            media.timestamp_ms,
            "info",
            "얼굴 방향과 시선을 별도로 관찰했습니다.",
            metrics,
            latency_ms=int((time.perf_counter() - started) * 1000),
        )


class UnavailableGazeAdapter:
    def __init__(self, reason: str) -> None:
        self.reason = reason

    async def infer(self, media: MediaPayload) -> AIResult:
        raise RuntimeError(self.reason)
