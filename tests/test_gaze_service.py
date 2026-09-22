from app.ai.base import AIResult
from app.modules.gaze.service import GazeStabilizer


def gaze_result(timestamp_ms: int, face_detected: bool, direction: str) -> AIResult:
    return AIResult(
        source="gaze",
        timestamp_ms=timestamp_ms,
        level="info",
        message="",
        metrics={
            "face_detected": face_detected,
            "gaze_direction": direction,
            "attention_state": "camera" if direction == "center" else "away",
            "quality": 0.9 if face_detected else 0.0,
            "confidence": 0.9 if face_detected else 0.0,
            "calibrated": True,
            "head_pose": {
                "yaw": 0.0 if face_detected else None,
                "pitch": 0.0 if face_detected else None,
                "roll": 0.0 if face_detected else None,
            },
            "away": face_detected and direction != "center",
        },
    )


def test_no_face_is_unknown_not_gaze_away() -> None:
    stabilizer = GazeStabilizer(warning_after_ms=2000)
    result = gaze_result(1000, face_detected=False, direction="unknown")

    stabilized = stabilizer.update(result)

    assert stabilized.metrics["attention_state"] == "unknown"
    assert stabilized.metrics["away"] is False
    assert "얼굴이 화면에서 벗어났습니다" not in stabilized.message


def test_calibration_requires_sixteen_good_center_frames() -> None:
    stabilizer = GazeStabilizer(calibration_frames=16)
    for index in range(15):
        current = stabilizer.update(gaze_result(index * 125, True, "center"))
        assert current.metrics["calibrated"] is False

    calibrated = stabilizer.update(gaze_result(15 * 125, True, "center"))

    assert calibrated.metrics["calibrated"] is True


def test_gaze_warning_requires_sustained_away_state() -> None:
    stabilizer = GazeStabilizer(warning_after_ms=2000)

    first = stabilizer.update(gaze_result(1000, True, "left"))
    transient = stabilizer.update(gaze_result(2500, True, "left"))
    sustained = stabilizer.update(gaze_result(3100, True, "left"))

    assert first.level == "info"
    assert transient.level == "info"
    assert sustained.level == "warning"
    assert "왼쪽" in sustained.message
