from collections import Counter
from typing import Any

from app.ai.base import AIResult


class FeedbackAggregator:
    def __init__(self) -> None:
        self.gaze_samples = 0
        self.gaze_away_count = 0
        self.gaze_away_duration_ms = 0
        self.speech_rates: list[float] = []
        self.fillers: Counter[str] = Counter()
        self.transcript_parts: list[str] = []
        self.timeline: list[dict[str, Any]] = []
        self.pronunciation_scores: list[float] = []
        self.pronunciation_confidences: list[float] = []
        self.script_progress_ratio = 0.0
        self.script_pace_deltas: list[int] = []

    def add(self, result: AIResult) -> None:
        if result.source == "gaze":
            self.gaze_samples += 1
            if result.metrics.get("away"):
                self.gaze_away_count += 1
                self.gaze_away_duration_ms += 333
        if result.source == "speech_rate":
            rate = float(result.metrics.get("syllables_per_minute", 0))
            if rate:
                self.speech_rates.append(rate)
            for item in result.metrics.get("filler_words", []):
                self.fillers[str(item["word"])] += int(item["count"])
            if result.transcript and result.is_final:
                self.transcript_parts.append(result.transcript)
        self.timeline.append(
            {
                "timestamp_ms": result.timestamp_ms,
                "source": result.source,
                "level": result.level,
                "metrics": result.metrics,
            }
        )
        if len(self.timeline) > 500:
            self.timeline = self.timeline[-500:]

    def snapshot(self) -> dict[str, Any]:
        avg_rate = sum(self.speech_rates) / len(self.speech_rates) if self.speech_rates else 0
        return {
            "gaze_away_count": self.gaze_away_count,
            "average_syllables_per_minute": round(avg_rate, 1),
            "filler_word_counts": dict(self.fillers),
            "pronunciation_clarity_score": self._average(self.pronunciation_scores),
            "script_completion_ratio": round(self.script_progress_ratio, 4),
        }

    @staticmethod
    def _average(values: list[float]) -> float | None:
        return round(sum(values) / len(values), 1) if values else None

    def add_pronunciation(self, result: dict[str, Any], timestamp_ms: int) -> None:
        score = result.get("pronunciation_clarity_score")
        if score is not None:
            self.pronunciation_scores.append(float(score))
            self.pronunciation_confidences.append(float(result.get("confidence", 0)))
        self.timeline.append(
            {
                "timestamp_ms": timestamp_ms,
                "source": "pronunciation",
                "level": "info" if score is None or float(score) >= 80 else "warning",
                "metrics": result,
            }
        )

    def add_script_progress(self, progress: dict[str, Any], timestamp_ms: int) -> None:
        self.script_progress_ratio = max(
            self.script_progress_ratio, float(progress.get("progress_ratio", 0))
        )
        self.script_pace_deltas.append(int(progress.get("pace_delta_ms", 0)))
        self.timeline.append(
            {
                "timestamp_ms": timestamp_ms,
                "source": "script_sync",
                "level": "info",
                "metrics": progress,
            }
        )

    def report(self) -> dict[str, Any]:
        avg_rate = sum(self.speech_rates) / len(self.speech_rates) if self.speech_rates else 0
        gaze_ratio = self.gaze_away_count / max(self.gaze_samples, 1)
        gaze_score = max(0.0, 100.0 - gaze_ratio * 100)
        rate_score = max(0.0, 100.0 - abs(avg_rate - 300) / 3) if avg_rate else 100.0
        filler_score = max(0.0, 100.0 - sum(self.fillers.values()) * 5)
        overall = gaze_score * 0.4 + rate_score * 0.35 + filler_score * 0.25
        pronunciation_score = self._average(self.pronunciation_scores)
        average_delta = self._average([float(abs(value)) for value in self.script_pace_deltas])
        time_adherence_score = (
            max(0.0, 100.0 - float(average_delta or 0) / 100) if self.script_pace_deltas else None
        )
        return {
            "overall_score": round(overall, 1),
            "gaze_score": round(gaze_score, 1),
            "speech_rate_score": round(rate_score, 1),
            "filler_word_score": round(filler_score, 1),
            "gaze_away_count": self.gaze_away_count,
            "gaze_away_duration_ms": self.gaze_away_duration_ms,
            "average_syllables_per_minute": round(avg_rate, 1),
            "filler_word_counts": dict(self.fillers),
            "transcript": " ".join(self.transcript_parts) or None,
            "timeline": self.timeline,
            "summary": self.snapshot(),
            "pronunciation_clarity_score": pronunciation_score,
            "script_completion_ratio": round(self.script_progress_ratio, 4),
            "time_adherence_score": round(time_adherence_score, 1)
            if time_adherence_score is not None
            else None,
            "gaze_metrics": {
                "away_count": self.gaze_away_count,
                "away_duration_ms": self.gaze_away_duration_ms,
            },
            "speech_rate_metrics": {
                "average_syllables_per_minute": round(avg_rate, 1),
                "filler_word_counts": dict(self.fillers),
            },
            "pronunciation_metrics": {
                "sample_count": len(self.pronunciation_scores),
                "average_confidence": self._average(self.pronunciation_confidences),
            },
            "script_sync_metrics": {
                "completion_ratio": round(self.script_progress_ratio, 4),
                "average_absolute_pace_delta_ms": average_delta,
            },
            "scoring_version": "v1",
        }
