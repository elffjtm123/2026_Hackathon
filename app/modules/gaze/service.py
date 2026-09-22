from dataclasses import dataclass
from statistics import median
from typing import Any

from app.ai.base import AIResult

GAZE_DIRECTIONS = {"center", "left", "right", "up", "down", "unknown"}
DIRECTION_LABELS = {
    "left": "왼쪽",
    "right": "오른쪽",
    "up": "위쪽",
    "down": "아래쪽",
}


@dataclass(frozen=True, slots=True)
class GazeObservation:
    face_detected: bool
    head_pose: dict[str, float | None]
    gaze_direction: str
    attention_state: str
    quality: float
    confidence: float
    calibrated: bool


def _number(value: Any) -> float | None:
    if isinstance(value, int | float):
        return float(value)
    return None


class GazeStabilizer:
    def __init__(
        self,
        *,
        calibration_frames: int = 0,
        warning_after_ms: int = 2000,
        warning_cooldown_ms: int = 5000,
        no_face_notice_ms: int = 1000,
        angle_threshold: float = 12.0,
        minimum_quality: float = 0.5,
    ) -> None:
        self.calibration_frames = max(0, calibration_frames)
        self.warning_after_ms = warning_after_ms
        self.warning_cooldown_ms = warning_cooldown_ms
        self.no_face_notice_ms = no_face_notice_ms
        self.angle_threshold = angle_threshold
        self.minimum_quality = minimum_quality
        self.calibration_yaw: list[float] = []
        self.calibration_pitch: list[float] = []
        self.baseline_yaw: float | None = None
        self.baseline_pitch: float | None = None
        self.state = "unknown"
        self.state_started_ms: int | None = None
        self.last_warning_ms: int | None = None

    def update(self, result: AIResult) -> AIResult:
        observation = self._observation(result.metrics)
        if self.calibration_frames and self.baseline_yaw is None:
            return self._calibrate(result, observation)

        direction = self._direction(observation)
        if not observation.face_detected or observation.quality < self.minimum_quality:
            attention_state = "unknown"
            direction = "unknown"
        elif direction == "center":
            attention_state = (
                observation.attention_state
                if observation.attention_state in {"camera", "screen"}
                else "camera"
            )
        elif direction in DIRECTION_LABELS:
            attention_state = "away"
        else:
            attention_state = "unknown"

        state_duration = self._update_state(attention_state, result.timestamp_ms)
        level = "info"
        if attention_state == "unknown":
            message = (
                "얼굴이 감지되지 않습니다. 카메라 안에 얼굴이 보이도록 조정해 주세요."
                if state_duration >= self.no_face_notice_ms
                else "시선 판단을 준비하고 있습니다."
            )
        elif attention_state == "away":
            label = DIRECTION_LABELS[direction]
            can_warn = (
                state_duration >= self.warning_after_ms
                and (
                    self.last_warning_ms is None
                    or result.timestamp_ms - self.last_warning_ms
                    >= self.warning_cooldown_ms
                )
            )
            if can_warn:
                level = "warning"
                self.last_warning_ms = result.timestamp_ms
                message = f"시선이 {label}으로 지속되고 있어요. 카메라를 바라봐 주세요."
            else:
                message = f"시선이 {label}을 향하고 있어요."
        elif attention_state == "screen":
            message = "화면을 자연스럽게 바라보고 있어요."
        else:
            message = "카메라를 안정적으로 바라보고 있어요."

        return self._result(
            result,
            observation,
            direction=direction,
            attention_state=attention_state,
            calibrated=True,
            level=level,
            message=message,
        )

    def _observation(self, metrics: dict[str, Any]) -> GazeObservation:
        pose = metrics.get("head_pose")
        pose = pose if isinstance(pose, dict) else {}
        direction = str(
            metrics.get("gaze_direction", metrics.get("direction", "unknown"))
        ).lower()
        if direction not in GAZE_DIRECTIONS:
            direction = "unknown"
        return GazeObservation(
            face_detected=metrics.get("face_detected") is True,
            head_pose={
                "yaw": _number(pose.get("yaw")),
                "pitch": _number(pose.get("pitch")),
                "roll": _number(pose.get("roll")),
            },
            gaze_direction=direction,
            attention_state=str(metrics.get("attention_state", "unknown")),
            quality=_number(metrics.get("quality")) or 0.0,
            confidence=_number(metrics.get("confidence")) or 0.0,
            calibrated=bool(metrics.get("calibrated", False)),
        )

    def _calibrate(
        self, result: AIResult, observation: GazeObservation
    ) -> AIResult:
        yaw = observation.head_pose["yaw"]
        pitch = observation.head_pose["pitch"]
        if (
            observation.face_detected
            and observation.quality >= self.minimum_quality
            and observation.gaze_direction == "center"
            and yaw is not None
            and pitch is not None
        ):
            self.calibration_yaw.append(yaw)
            self.calibration_pitch.append(pitch)

        calibrated = len(self.calibration_yaw) >= self.calibration_frames
        if calibrated:
            self.baseline_yaw = median(self.calibration_yaw)
            self.baseline_pitch = median(self.calibration_pitch)
            attention_state = "camera"
            direction = "center"
            message = "시선 보정이 완료되었습니다."
        else:
            attention_state = "unknown"
            direction = "unknown"
            message = (
                "카메라를 바라보며 보정 중 "
                f"({len(self.calibration_yaw)}/{self.calibration_frames})"
            )
        self._update_state(attention_state, result.timestamp_ms)
        return self._result(
            result,
            observation,
            direction=direction,
            attention_state=attention_state,
            calibrated=calibrated,
            level="info",
            message=message,
        )

    def _direction(self, observation: GazeObservation) -> str:
        yaw = observation.head_pose["yaw"]
        pitch = observation.head_pose["pitch"]
        if (
            self.baseline_yaw is None
            or self.baseline_pitch is None
            or yaw is None
            or pitch is None
        ):
            return observation.gaze_direction
        yaw_delta = yaw - self.baseline_yaw
        pitch_delta = pitch - self.baseline_pitch
        if abs(yaw_delta) >= abs(pitch_delta) and abs(yaw_delta) > self.angle_threshold:
            return "right" if yaw_delta > 0 else "left"
        if abs(pitch_delta) > self.angle_threshold:
            return "down" if pitch_delta > 0 else "up"
        return "center"

    def _update_state(self, state: str, timestamp_ms: int) -> int:
        if state != self.state or self.state_started_ms is None:
            self.state = state
            self.state_started_ms = timestamp_ms
            return 0
        return max(0, timestamp_ms - self.state_started_ms)

    @staticmethod
    def _result(
        result: AIResult,
        observation: GazeObservation,
        *,
        direction: str,
        attention_state: str,
        calibrated: bool,
        level: str,
        message: str,
    ) -> AIResult:
        metrics = {
            **result.metrics,
            "face_detected": observation.face_detected,
            "head_pose": observation.head_pose,
            "gaze_direction": direction,
            "direction": direction,
            "attention_state": attention_state,
            "quality": observation.quality,
            "confidence": observation.confidence,
            "calibrated": calibrated,
            "away": calibrated and attention_state == "away",
        }
        return AIResult(
            source=result.source,
            timestamp_ms=result.timestamp_ms,
            level=level,
            message=message,
            metrics=metrics,
            transcript=result.transcript,
            is_final=result.is_final,
            latency_ms=result.latency_ms,
        )
