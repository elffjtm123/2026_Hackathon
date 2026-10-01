import math
from collections import deque
from dataclasses import dataclass, field
from statistics import median
from typing import Any

from app.ai.base import AIResult

GAZE_DIRECTIONS = {"center", "left", "right", "up", "down", "unknown"}
DIRECTION_LABELS = {
    "center": "정면",
    "left": "왼쪽",
    "right": "오른쪽",
    "up": "위쪽",
    "down": "아래쪽",
}


@dataclass(frozen=True, slots=True)
class GazeObservation:
    face_detected: bool
    head_pose: dict[str, float | None]
    gaze_angles: dict[str, float | None]
    face_detection_confidence: float | None
    quality_flags: list[str]
    timestamp_ms: int
    bbox: tuple[int, int, int, int] | None = None
    quality_measurements: dict[str, float] = field(default_factory=dict)


def _number(value: Any) -> float | None:
    return (
        float(value)
        if isinstance(value, int | float) and not isinstance(value, bool) and math.isfinite(value)
        else None
    )


def direction_from_angles(yaw: float | None, pitch: float | None, threshold: float = 12.0) -> str:
    if yaw is None or pitch is None:
        return "unknown"
    if max(abs(yaw), abs(pitch)) <= threshold:
        return "center"
    if abs(yaw) >= abs(pitch):
        return "right" if yaw > 0 else "left"
    return "up" if pitch > 0 else "down"


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
        return_threshold: float = 8.0,
        calibration_duration_ms: int = 750,
        calibration_timeout_ms: int = 15000,
        head_limit: float = 15.0,
        spread_limit: float = 4.0,
        smoothing_tau_ms: float = 250.0,
    ) -> None:
        self.calibration_frames = max(0, calibration_frames)
        self.warning_after_ms, self.warning_cooldown_ms = warning_after_ms, warning_cooldown_ms
        self.no_face_notice_ms, self.minimum_quality = no_face_notice_ms, minimum_quality
        self.angle_threshold, self.return_threshold = angle_threshold, return_threshold
        self.calibration_duration_ms, self.calibration_timeout_ms = (
            calibration_duration_ms,
            calibration_timeout_ms,
        )
        self.head_limit, self.spread_limit, self.smoothing_tau_ms = (
            head_limit,
            spread_limit,
            smoothing_tau_ms,
        )
        self.window: deque[tuple[int, float, float, float, float]] = deque(
            maxlen=max(128, calibration_frames)
        )
        self.baseline_yaw: float | None = None if calibration_frames else 0.0
        self.baseline_pitch: float | None = None if calibration_frames else 0.0
        self.calibration_started_ms: int | None = None
        self.calibration_status = "collecting" if calibration_frames else "complete"
        self.recalibration_required = False
        self.last_timestamp_ms: int | None = None
        self.last_valid_ms: int | None = None
        self.smooth: tuple[float, float] | None = None
        self.state = "unknown"
        self.state_started_ms: int | None = None
        self.last_warning_ms: int | None = None

    def begin_calibration(self, timestamp_ms: int) -> None:
        self.window.clear()
        self.baseline_yaw = self.baseline_pitch = None
        self.calibration_started_ms = timestamp_ms
        self.calibration_status = "collecting"
        self.recalibration_required = False
        self.smooth = None
        self.state, self.state_started_ms = "unknown", None
        self.last_timestamp_ms = self.last_valid_ms = None
        self.last_warning_ms = None

    def invalidate(self, reason: str) -> None:
        self.window.clear()
        self.baseline_yaw = self.baseline_pitch = None
        self.recalibration_required = True
        self.calibration_status = reason
        self.smooth = None
        self.state, self.state_started_ms = "unknown", None

    def update(self, result: AIResult) -> AIResult:
        m, timestamp = result.metrics, result.timestamp_ms
        flags = list(m.get("quality_flags", []))
        pose, gaze = m.get("head_pose", {}), m.get("gaze_angles", {})
        hy, hp = _number(pose.get("yaw")), _number(pose.get("pitch"))
        gy, gp = _number(gaze.get("yaw")), _number(gaze.get("pitch"))
        if m.get("face_detected") is not True and "no_face" not in flags:
            flags.append("no_face")
        if (_number(m.get("quality")) or 0.0) < self.minimum_quality and not flags:
            flags.append("low_quality")
        previous = self.last_timestamp_ms
        if previous is not None and timestamp <= previous:
            return self._result(
                result,
                "unknown",
                "unknown",
                "unknown",
                "info",
                "지난 관찰값은 사용하지 않습니다.",
                [*flags, "stale_sample"],
            )
        self.last_timestamp_ms = timestamp
        if self.calibration_status != "collecting":
            if "face_changed" in flags or "camera_changed" in flags:
                self.invalidate("input_changed")
            if self.last_valid_ms is not None and timestamp - self.last_valid_ms > 3000:
                self.invalidate("face_lost")
        valid = not flags
        head = direction_from_angles(hy, hp) if valid else "unknown"
        if valid:
            self.last_valid_ms = timestamp
        if self.calibration_status == "collecting":
            if self.calibration_started_ms is None:
                self.calibration_started_ms = timestamp
            if timestamp - self.calibration_started_ms > self.calibration_timeout_ms:
                self.invalidate("timeout")
            else:
                accepted = (
                    valid
                    and all(v is not None for v in (hy, hp, gy, gp))
                    and abs(hy or 0) <= self.head_limit
                    and abs(hp or 0) <= self.head_limit
                )
                if not accepted or (previous is not None and timestamp - previous > 1500):
                    self.window.clear()
                if accepted:
                    item = (timestamp, hy or 0.0, hp or 0.0, gy or 0.0, gp or 0.0)
                    self.window.append(item)
                    if len(self.window) >= 8:
                        # ponytail: median dispersion tolerates isolated model spikes;
                        # this checks stability, not the user's actual fixation target.
                        unstable = False
                        for axis in range(1, 5):
                            center = median(row[axis] for row in self.window)
                            spread = 2 * median(abs(row[axis] - center) for row in self.window)
                            unstable |= spread > self.spread_limit
                        if unstable:
                            self.window.clear()
                            self.window.append(item)
                if (
                    len(self.window) >= max(1, self.calibration_frames)
                    and timestamp - self.window[0][0] >= self.calibration_duration_ms
                ):
                    self.baseline_yaw = median(row[3] for row in self.window)
                    self.baseline_pitch = median(row[4] for row in self.window)
                    self.calibration_status = "complete"
                    self.smooth = None
                else:
                    if "no_face" in flags:
                        reason = "얼굴이 감지되지 않습니다."
                    elif flags:
                        reason = (
                            "얼굴이 작거나 흐립니다. 조명과 눈 상태를 확인하고 가까이 와 주세요."
                        )
                    elif hy is None or hp is None:
                        reason = "얼굴 방향을 측정하지 못했습니다."
                    elif abs(hy) > self.head_limit or abs(hp) > self.head_limit:
                        reason = "얼굴을 정면으로 돌려 주세요."
                    elif gy is None or gp is None:
                        reason = "눈 시선을 측정하지 못했습니다."
                    else:
                        reason = "카메라를 바라보며 얼굴과 눈을 안정적으로 유지해 주세요."
                    return self._result(
                        result,
                        "unknown",
                        "unknown",
                        head,
                        "info",
                        f"{reason} 보정 중 ({len(self.window)}/{self.calibration_frames})",
                        flags,
                    )
        if self.recalibration_required:
            return self._result(
                result,
                "unknown",
                "unknown",
                head,
                "info",
                "다시 보정이 필요합니다. 정면을 바라보고 다시 보정을 눌러 주세요.",
                flags,
            )
        if (
            not valid
            or gy is None
            or gp is None
            or self.baseline_yaw is None
            or self.baseline_pitch is None
        ):
            self.smooth = None
            self.state, self.state_started_ms = "unknown", timestamp
            message = (
                "얼굴 방향만 확인하고 있습니다. 눈 시선은 판단할 수 없습니다."
                if head != "unknown"
                else "시선을 판단할 수 없습니다. 얼굴 위치·조명·눈 상태를 확인해 주세요."
            )
            return self._result(result, "unknown", "unknown", head, "info", message, flags)
        if previous is not None and timestamp - previous > 1500:
            self.smooth = None
            self.state, self.state_started_ms = "unknown", timestamp
        angles = (gy - self.baseline_yaw, gp - self.baseline_pitch)
        if self.smooth is not None and previous is not None:
            alpha = 1 - math.exp(-(timestamp - previous) / self.smoothing_tau_ms)
            angles = (
                self.smooth[0] + alpha * (angles[0] - self.smooth[0]),
                self.smooth[1] + alpha * (angles[1] - self.smooth[1]),
            )
        self.smooth = angles
        threshold = self.return_threshold if self.state == "away" else self.angle_threshold
        direction = direction_from_angles(*angles, threshold)
        state = "baseline" if direction == "center" else "away"
        if state != self.state:
            self.state, self.state_started_ms = state, timestamp
        duration = timestamp - (
            self.state_started_ms if self.state_started_ms is not None else timestamp
        )
        level = "info"
        if state == "baseline":
            message = "시선이 보정 기준 근처에 있습니다. 카메라·화면 응시 여부는 구분하지 않습니다."
        else:
            label = DIRECTION_LABELS[direction]
            warning = duration >= self.warning_after_ms and (
                self.last_warning_ms is None
                or timestamp - self.last_warning_ms >= self.warning_cooldown_ms
            )
            if warning:
                level, self.last_warning_ms = "warning", timestamp
                prefix = "얼굴은 정면이지만 " if head == "center" else ""
                message = (
                    f"{prefix}시선이 {label}으로 지속되고 있어요. "
                    "보정 때 바라본 방향을 확인해 주세요."
                )
            else:
                message = f"시선 추정값이 보정 기준보다 {label}을 향하고 있어요."
        return self._result(result, direction, state, head, level, message, flags)

    def _result(
        self,
        result: AIResult,
        direction: str,
        state: str,
        head: str,
        level: str,
        message: str,
        flags: list[str],
    ) -> AIResult:
        metrics = {
            **result.metrics,
            "gaze_direction": direction,
            "direction": direction,
            "head_direction": head,
            "attention_state": state,
            "quality_flags": flags,
            "calibrated": self.calibration_status == "complete",
            "calibration_status": self.calibration_status,
            "calibration_progress": min(len(self.window), self.calibration_frames),
            "calibration_target": self.calibration_frames,
            "recalibration_required": self.recalibration_required,
            "away": state == "away",
        }
        return AIResult(
            result.source,
            result.timestamp_ms,
            level,
            message,
            metrics,
            result.transcript,
            result.is_final,
            result.latency_ms,
        )
