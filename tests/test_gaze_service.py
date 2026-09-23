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


def test_calibration_accepts_unclassified_uniface_angles() -> None:
    stabilizer = GazeStabilizer(calibration_frames=2)
    first = gaze_result(0, True, "unknown")
    second = gaze_result(125, True, "unknown")

    assert stabilizer.update(first).metrics["calibrated"] is False
    assert stabilizer.update(second).metrics["calibrated"] is True


def test_calibration_explains_why_no_frames_are_accepted() -> None:
    stabilizer = GazeStabilizer(calibration_frames=16)
    no_face = stabilizer.update(gaze_result(0, False, "unknown"))
    too_small = gaze_result(125, True, "unknown")
    too_small.metrics["quality"] = 0.2
    low_quality = stabilizer.update(too_small)

    assert "얼굴이 감지되지" in no_face.message
    assert "가까이" in low_quality.message
    assert low_quality.metrics["calibrated"] is False


def test_gaze_warning_requires_sustained_away_state() -> None:
    stabilizer = GazeStabilizer(warning_after_ms=2000)

    first = stabilizer.update(gaze_result(1000, True, "left"))
    transient = stabilizer.update(gaze_result(2500, True, "left"))
    sustained = stabilizer.update(gaze_result(3100, True, "left"))

    assert first.level == "info"
    assert transient.level == "info"
    assert sustained.level == "warning"
    assert "왼쪽" in sustained.message
