from uuid import uuid4

import numpy as np
import pytest

from app.ai.base import MediaPayload
from app.ai.uniface_gaze import UniFaceGazeAdapter


class FakeFace:
    bbox = np.array([20, 10, 180, 190], dtype=np.float32)
    confidence = 0.95


class FakeDetector:
    def detect(self, _frame: np.ndarray) -> list[FakeFace]:
        return [FakeFace()]


class FakeEstimate:
    pitch = 0.02
    yaw = -0.35


class FakeEstimator:
    def estimate(self, _face_crop: np.ndarray) -> FakeEstimate:
        return FakeEstimate()


@pytest.mark.asyncio
async def test_uniface_adapter_maps_angles_to_contract() -> None:
    adapter = UniFaceGazeAdapter(
        detector=FakeDetector(),
        estimator=FakeEstimator(),
        decoder=lambda _payload: np.zeros((200, 200, 3), dtype=np.uint8),
    )

    result = await adapter.infer(MediaPayload(uuid4(), 1000, b"jpeg"))

    assert result.metrics["face_detected"] is True
    assert result.metrics["gaze_direction"] == "unknown"
    assert round(result.metrics["head_pose"]["yaw"]) == -20
    assert result.metrics["quality"] > 0


@pytest.mark.asyncio
async def test_uniface_adapter_reports_no_face_without_marking_away() -> None:
    adapter = UniFaceGazeAdapter(
        detector=type("NoFaces", (), {"detect": lambda self, frame: []})(),
        estimator=FakeEstimator(),
        decoder=lambda _payload: np.zeros((200, 200, 3), dtype=np.uint8),
    )

    result = await adapter.infer(MediaPayload(uuid4(), 1000, b"jpeg"))

    assert result.metrics["face_detected"] is False
    assert result.metrics["attention_state"] == "unknown"
    assert result.metrics["away"] is False
