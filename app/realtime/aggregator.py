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
        }

    def report(self) -> dict[str, Any]:
        avg_rate = sum(self.speech_rates) / len(self.speech_rates) if self.speech_rates else 0
        gaze_ratio = self.gaze_away_count / max(self.gaze_samples, 1)
        gaze_score = max(0.0, 100.0 - gaze_ratio * 100)
        rate_score = max(0.0, 100.0 - abs(avg_rate - 300) / 3) if avg_rate else 100.0
        filler_score = max(0.0, 100.0 - sum(self.fillers.values()) * 5)
        overall = gaze_score * 0.4 + rate_score * 0.35 + filler_score * 0.25
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
        }
