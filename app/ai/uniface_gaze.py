import asyncio
import math
import time
from collections.abc import Callable
from typing import Any

from app.ai.base import AIResult, MediaPayload


class UniFaceGazeAdapter:
    def __init__(
        self,
        detector: Any = None,
        estimator: Any = None,
        decoder: Callable[[bytes], Any] | None = None,
    ) -> None:
        import numpy as np

        self.np = np
        if decoder is None:
            import cv2

            decoder = lambda payload: cv2.imdecode(  # noqa: E731
                np.frombuffer(payload, dtype=np.uint8), cv2.IMREAD_COLOR
            )
        if detector is None or estimator is None:
            import onnxruntime as ort
            from uniface.detection import RetinaFace
            from uniface.gaze import MobileGaze

            available = set(ort.get_available_providers())
            providers = [
                provider
                for provider in ("CoreMLExecutionProvider", "CPUExecutionProvider")
                if provider in available
            ]
            detector = detector or RetinaFace(providers=providers)
            estimator = estimator or MobileGaze(providers=providers)
        self.detector = detector
        self.estimator = estimator
        self.decoder = decoder

    async def infer(self, media: MediaPayload) -> AIResult:
        started = time.perf_counter()
        return await asyncio.to_thread(self._infer_sync, media, started)

    def _infer_sync(self, media: MediaPayload, started: float) -> AIResult:
        frame = self.decoder(media.payload)
        if frame is None or getattr(frame, "size", 0) == 0:
            return self._no_face(media, started, "영상 프레임을 읽을 수 없습니다.")

        faces = self.detector.detect(frame)
        if not faces:
            return self._no_face(media, started, "얼굴이 감지되지 않았습니다.")

        frame_height, frame_width = frame.shape[:2]
        face = max(faces, key=lambda item: self._bbox_area(item.bbox))
        x1, y1, x2, y2 = [int(value) for value in face.bbox[:4]]
        x1, x2 = max(0, x1), min(frame_width, x2)
        y1, y2 = max(0, y1), min(frame_height, y2)
        face_crop = frame[y1:y2, x1:x2]
        if face_crop.size == 0:
            return self._no_face(media, started, "얼굴 영역을 읽을 수 없습니다.")

        estimate = self.estimator.estimate(face_crop)
        area_ratio = ((x2 - x1) * (y2 - y1)) / max(1, frame_width * frame_height)
        detector_confidence = float(getattr(face, "confidence", 0.0))
        quality = round(
            max(0.0, min(1.0, detector_confidence * min(1.0, area_ratio / 0.2))),
            3,
        )
        pitch = math.degrees(float(estimate.pitch))
        yaw = math.degrees(float(estimate.yaw))
        return AIResult(
            source="gaze",
            timestamp_ms=media.timestamp_ms,
            level="info",
            message="시선 관찰값을 계산했습니다.",
            metrics={
                "face_detected": True,
                "head_pose": {"yaw": yaw, "pitch": pitch, "roll": None},
                "gaze_direction": "unknown",
                "attention_state": "unknown",
                "quality": quality,
                "confidence": detector_confidence,
                "calibrated": False,
                "away": False,
                "face_area_ratio": area_ratio,
            },
            latency_ms=int((time.perf_counter() - started) * 1000),
        )

    @staticmethod
    def _bbox_area(bbox: Any) -> float:
        return max(0.0, float(bbox[2] - bbox[0])) * max(
            0.0, float(bbox[3] - bbox[1])
        )

    @staticmethod
    def _no_face(media: MediaPayload, started: float, message: str) -> AIResult:
        return AIResult(
            source="gaze",
            timestamp_ms=media.timestamp_ms,
            level="info",
            message=message,
            metrics={
                "face_detected": False,
                "head_pose": {"yaw": None, "pitch": None, "roll": None},
                "gaze_direction": "unknown",
                "attention_state": "unknown",
                "quality": 0.0,
                "confidence": 0.0,
                "calibrated": False,
                "away": False,
                "face_area_ratio": 0.0,
            },
            latency_ms=int((time.perf_counter() - started) * 1000),
        )


class UnavailableGazeAdapter:
    def __init__(self, reason: str) -> None:
        self.reason = reason

    async def infer(self, media: MediaPayload) -> AIResult:
        raise RuntimeError(self.reason)
