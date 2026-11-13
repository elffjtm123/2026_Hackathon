"""Bookkeeping for a live STT model-comparison session; the pipeline only reports events."""

import copy
from typing import Any

from app.ai.base import AIResult


class ExperimentRecorder:
    """Record events in, get one ``report["comparison"]`` summary out.

    ``info`` is the run description sent with ``session.ready``; the summary is that
    description plus per-source performance, error counts and queue pressure.
    """

    def __init__(self, info: dict[str, Any]) -> None:
        self._info = dict(info)
        self._performance: dict[str, dict[str, Any]] = {}
        self._latency_totals: dict[str, float] = {}
        self._errors: dict[str, int] = {}
        self._audio_queue_peak = 0

    @property
    def info(self) -> dict[str, Any]:
        return self._info

    def annotate(self, **fields: Any) -> None:
        self._info.update(fields)

    def record_error(self, code: str) -> None:
        self._errors[code] = self._errors.get(code, 0) + 1

    def record_audio_queue(self, depth: int) -> None:
        self._audio_queue_peak = max(self._audio_queue_peak, depth)

    def record_result(self, result: AIResult, now_ms: int) -> None:
        stats = self._performance.setdefault(
            result.source,
            {
                "observations": 0,
                "measured_latency_count": 0,
                "average_inference_ms": None,
                "max_result_age_ms": 0,
            },
        )
        stats["observations"] += 1
        if result.latency_ms is not None:
            total = self._latency_totals.get(result.source, 0.0) + result.latency_ms
            self._latency_totals[result.source] = total
            stats["measured_latency_count"] += 1
            stats["average_inference_ms"] = round(total / stats["measured_latency_count"], 2)
        stats["max_result_age_ms"] = max(stats["max_result_age_ms"], now_ms - result.timestamp_ms)

    def summary(self, dropped_video_frames: int) -> dict[str, Any]:
        return {
            **copy.deepcopy(self._info),
            "performance": copy.deepcopy(self._performance),
            "errors": dict(self._errors),
            "audio_queue_peak": self._audio_queue_peak,
            "dropped_video_frames": dropped_video_frames,
        }
