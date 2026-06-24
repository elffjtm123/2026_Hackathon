import asyncio
import time
from typing import Any

from app.ai.base import AIResult, MediaPayload


class VideoGazeAdapter:
    def __init__(self) -> None:
        import cv2
        import mediapipe as mp
        import numpy as np

        if not hasattr(mp, "solutions"):
            raise RuntimeError("installed mediapipe package does not provide mp.solutions")

        import video

        video.CALIBRATION_FRAMES = 8
        video.SMOOTHING_WINDOW = 3
        self.cv2 = cv2
        self.np = np
        self.video = video
        self.extractor = video.FaceFeatureExtractor(static_mode=False)
        self.classifier = video.CalibratedGazeClassifier(None, None)

    async def infer(self, media: MediaPayload) -> AIResult:
        started = time.perf_counter()
        return await asyncio.to_thread(self._infer_sync, media, started)

    def _infer_sync(self, media: MediaPayload, started: float) -> AIResult:
        buffer = self.np.frombuffer(media.payload, dtype=self.np.uint8)
        frame = self.cv2.imdecode(buffer, self.cv2.IMREAD_COLOR)
        if frame is not None:
            frame = self.cv2.flip(frame, 1)
        features = self.extractor.extract(frame) if frame is not None else None
        gaze = self.classifier.predict(features)
        debug = self.classifier.last_debug
        away = gaze not in {"CENTER"}
        direction = self._direction(gaze)

        if gaze == "NO_FACE":
            message = "얼굴이 감지되지 않습니다. 카메라 앞으로 이동하세요."
        elif away:
            message = self.video.make_feedback(
                {
                    "current_gaze": gaze,
                    "non_center_duration": 2.0,
                }
            )
        else:
            message = "시선 처리가 안정적입니다."

        return AIResult(
            source="gaze",
            timestamp_ms=media.timestamp_ms,
            level="warning" if away else "info",
            message=message,
            metrics={
                "direction": direction,
                "away": away,
                "confidence": self._confidence(debug),
                "raw": gaze,
                "calibrated": bool(debug.get("calibrated")),
            },
            latency_ms=int((time.perf_counter() - started) * 1000),
        )

    def close(self) -> None:
        self.extractor.close()

    @staticmethod
    def _direction(gaze: str) -> str:
        mapping = {
            "CENTER": "center",
            "LEFT": "left",
            "RIGHT": "right",
            "UP": "up",
            "DOWN": "down",
            "NO_FACE": "away",
        }
        return mapping.get(gaze, "unknown")

    @staticmethod
    def _confidence(debug: dict[str, Any]) -> float:
        if not debug.get("calibrated"):
            return 0.5
        movement = max(
            abs(float(debug.get("d_head_x", 0.0))),
            abs(float(debug.get("d_head_y", 0.0))),
            abs(float(debug.get("d_avg_x", 0.0))),
            abs(float(debug.get("d_avg_y", 0.0))),
        )
        return round(max(0.55, min(0.95, 1.0 - movement)), 2)
