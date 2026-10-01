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
            "gaze_angles": {
                "yaw": {"left": -20.0, "right": 20.0}.get(direction, 0.0),
                "pitch": {"up": 20.0, "down": -20.0}.get(direction, 0.0),
            },
            "quality_flags": [] if face_detected else ["no_face"],
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
    second = gaze_result(1500, True, "unknown")

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


def test_sideways_head_rejects_calibration():
    stabilizer = GazeStabilizer(calibration_frames=16)
    for index in range(20):
        raw = gaze_result(index * 125, True, "center")
        raw.metrics["head_pose"]["yaw"] = 25
        result = stabilizer.update(raw)
    assert not result.metrics["calibrated"]
    assert result.metrics["calibration_progress"] == 0


def test_nonconsecutive_or_moving_frames_reset_window():
    stabilizer = GazeStabilizer(calibration_frames=16)
    for index in range(8):
        stabilizer.update(gaze_result(index * 125, True, "center"))
    missing = stabilizer.update(gaze_result(1000, False, "unknown"))
    assert missing.metrics["calibration_progress"] == 0
    for index in range(8):
        raw = gaze_result(1125 + index * 125, True, "center")
        raw.metrics["gaze_angles"]["yaw"] = index * 8
        result = stabilizer.update(raw)
    assert result.metrics["calibration_progress"] <= 1
    assert not result.metrics["calibrated"]


def test_quick_calibration_tolerates_occasional_model_jitter():
    stabilizer = GazeStabilizer(calibration_frames=8)
    stabilizer.begin_calibration(0)
    for index in range(8):
        raw = gaze_result(index * 125, True, "center")
        raw.metrics["gaze_angles"]["yaw"] = 8 if index in (2, 6) else 0
        result = stabilizer.update(raw)
    assert result.metrics["calibrated"]
    assert stabilizer.baseline_yaw == 0


def test_15_second_timeout_requires_explicit_retry():
    stabilizer = GazeStabilizer(calibration_frames=16)
    stabilizer.begin_calibration(0)
    timed = stabilizer.update(gaze_result(15001, False, "unknown"))
    assert timed.metrics["calibration_status"] == "timeout"
    for index in range(16):
        result = stabilizer.update(gaze_result(16000 + index * 125, True, "center"))
    assert not result.metrics["calibrated"]
    stabilizer.begin_calibration(19000)
    for index in range(16):
        result = stabilizer.update(gaze_result(19000 + index * 125, True, "center"))
    assert result.metrics["calibrated"]


def test_up_positive_pitch_is_up_without_camera_target_claim():
    stabilizer = GazeStabilizer()
    result = stabilizer.update(gaze_result(0, True, "up"))
    assert result.metrics["gaze_direction"] == "up"
    centered = GazeStabilizer().update(gaze_result(0, True, "center"))
    assert centered.metrics["attention_state"] == "baseline"
    assert "카메라를 안정적으로" not in centered.message


def test_hysteresis_and_sustained_warning():
    stabilizer = GazeStabilizer()
    for timestamp in [0, 500, 1000, 1500, 2000]:
        result = stabilizer.update(gaze_result(timestamp, True, "right"))
    assert result.level == "warning"
    raw = gaze_result(2500, True, "right")
    raw.metrics["gaze_angles"]["yaw"] = 10
    result = stabilizer.update(raw)
    assert result.metrics["attention_state"] == "away"
    for timestamp in [3000, 3500, 4000]:
        result = stabilizer.update(gaze_result(timestamp, True, "center"))
    assert result.metrics["attention_state"] == "baseline"


def test_no_face_and_camera_change_require_recalibration():
    stabilizer = GazeStabilizer()
    stabilizer.update(gaze_result(0, True, "center"))
    stabilizer.update(gaze_result(125, False, "unknown"))
    result = stabilizer.update(gaze_result(3200, True, "center"))
    assert result.metrics["recalibration_required"]
    assert result.metrics["attention_state"] == "unknown"
    stabilizer.begin_calibration(3300)
    stabilizer.invalidate("camera_changed")
    result = stabilizer.update(gaze_result(3400, True, "center"))
    assert result.metrics["recalibration_required"]


def test_head_only_is_not_used_as_eye_gaze():
    raw = gaze_result(0, True, "center")
    raw.metrics["gaze_angles"] = {"yaw": None, "pitch": None}
    result = GazeStabilizer().update(raw)
    assert result.metrics["head_direction"] == "center"
    assert result.metrics["gaze_direction"] == "unknown"
    assert result.metrics["attention_state"] == "unknown"
    assert "얼굴 방향만" in result.message


def test_no_auto_rebaseline_and_stale_sample_not_used():
    stabilizer = GazeStabilizer(calibration_frames=2)
    stabilizer.update(gaze_result(0, True, "center"))
    stabilizer.update(gaze_result(1500, True, "center"))
    for timestamp in range(1600, 4000, 125):
        result = stabilizer.update(gaze_result(timestamp, True, "right"))
    assert result.metrics["attention_state"] == "away"
    stale = stabilizer.update(gaze_result(0, True, "center"))
    assert stale.metrics["attention_state"] == "unknown"
    assert stabilizer.baseline_yaw == 0


def test_faster_input_still_calibrates_after_stable_duration():
    stabilizer = GazeStabilizer(calibration_frames=16)
    for index in range(50):
        result = stabilizer.update(gaze_result(index * 33, True, "center"))
    assert result.metrics["calibrated"]


def test_face_change_during_initial_calibration_restarts_window_not_session():
    stabilizer = GazeStabilizer(calibration_frames=16)
    for index in range(8):
        stabilizer.update(gaze_result(index * 125, True, "center"))
    changed = gaze_result(1000, True, "center")
    changed.metrics["quality_flags"] = ["face_changed"]
    stabilizer.update(changed)
    for index in range(16):
        result = stabilizer.update(gaze_result(1125 + index * 125, True, "center"))
    assert result.metrics["calibrated"]
