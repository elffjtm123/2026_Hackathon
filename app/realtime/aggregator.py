from collections import Counter
from typing import Any

from app.ai.base import AIResult
from app.modules.speech.analysis import filler_counts
from app.modules.speech.text import merge_transcript


class FeedbackAggregator:
    def __init__(self) -> None:
        self.gaze_samples = 0
        self.gaze_observations: list[tuple[int, bool, bool]] = []
        self.gaze_away_count = 0
        self.gaze_away_duration_ms = 0
        self.last_gaze_timestamp_ms: int | None = None
        self.last_gaze_was_away = False
        self.speech_rates: list[float] = []
        self.seen_utterances: set[tuple[str, int]] = set()
        self.syllable_count = 0
        self.voiced_ms = 0
        self.repeat_count = 0
        self.speech_warning_episodes = 0
        self.last_speech_pace = "unknown"
        self.fillers: Counter[str] = Counter()
        self.transcript = ""
        self.timeline: list[dict[str, Any]] = []
        self.pronunciation_scores: list[float] = []
        self.pronunciation_confidences: list[float] = []
        self.script_progress_ratio = 0.0
        self.script_alignment_observed = False
        self.script_pace_deltas: list[int] = []

    def add(self, result: AIResult) -> bool:
        if result.source == "speech_rate" and result.is_final:
            identity = result.metrics.get("utterance_id")
            if identity is not None:
                key = (str(identity), int(result.metrics.get("revision", 1)))
                if key in self.seen_utterances:
                    return False
                self.seen_utterances.add(key)
        if result.source == "gaze":
            self.gaze_samples += 1
            if self.last_gaze_was_away and self.last_gaze_timestamp_ms is not None:
                self.gaze_away_duration_ms += max(
                    0, result.timestamp_ms - self.last_gaze_timestamp_ms
                )
            current_away = (
                bool(result.metrics.get("away"))
                and bool(result.metrics.get("face_detected"))
                and float(result.metrics.get("quality", 0) or 0) >= 0.5
            )
            if current_away and not self.last_gaze_was_away:
                self.gaze_away_count += 1
            self.last_gaze_timestamp_ms = result.timestamp_ms
            self.last_gaze_was_away = current_away
            valid = (
                bool(result.metrics.get("face_detected"))
                and bool(result.metrics.get("calibrated"))
                and float(result.metrics.get("quality", 0) or 0) >= 0.5
                and result.metrics.get("attention_state")
                in {"away", "baseline", "camera", "screen"}
            )
            self.gaze_observations.append((result.timestamp_ms, valid, current_away and valid))
        if result.source == "speech_rate" and result.is_final:
            rate = float(result.metrics.get("syllables_per_minute", 0) or 0)
            if rate:
                self.speech_rates.append(rate)
            if result.transcript:
                if "utterance_id" in result.metrics:
                    self.transcript = " ".join(filter(None, [self.transcript, result.transcript]))
                    self.fillers.update(result.metrics.get("filler_counts", {}))
                    count = int(result.metrics.get("syllable_count", 0))
                    if count:
                        self.syllable_count += count
                        self.voiced_ms += int(result.metrics.get("voiced_ms", 0))
                    self.repeat_count += int(result.metrics.get("repeat_count", 0))
                else:
                    # v1 external adapters retain their historical overlap contract.
                    self.transcript, novel = merge_transcript(self.transcript, result.transcript)
                    self.fillers.update(filler_counts(novel)[0])
        if result.source == "speech_rate":
            pace = result.metrics.get("pace", "unknown")
            if pace in {"fast", "slow"} and pace != self.last_speech_pace:
                self.speech_warning_episodes += 1
            self.last_speech_pace = pace
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
        return True

    def average_speech_rate(self) -> float:
        if self.voiced_ms:
            return self.syllable_count * 60_000 / self.voiced_ms
        return sum(self.speech_rates) / len(self.speech_rates) if self.speech_rates else 0

    def snapshot(self) -> dict[str, Any]:
        avg_rate = self.average_speech_rate()
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
            if result.get("confidence") is not None:
                self.pronunciation_confidences.append(float(result["confidence"]))
        self.timeline.append(
            {
                "timestamp_ms": timestamp_ms,
                "source": "pronunciation",
                "level": "info" if score is None or float(score) >= 80 else "warning",
                "metrics": result,
            }
        )

    def add_script_progress(self, progress: dict[str, Any], timestamp_ms: int) -> None:
        self.script_alignment_observed = True
        self.script_progress_ratio = max(
            self.script_progress_ratio, float(progress.get("progress_ratio", 0))
        )
        if (
            progress.get("alignment_status") == "matched"
            and progress.get("pace_delta_ms") is not None
        ):
            self.script_pace_deltas.append(int(progress["pace_delta_ms"]))
        self.timeline.append(
            {
                "timestamp_ms": timestamp_ms,
                "source": "script_sync",
                "level": "info",
                "metrics": progress,
            }
        )

    def report(
        self,
        running_started_ms: int = 0,
        end_ms: int | None = None,
        *,
        settings: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        settings = settings or {}
        if end_ms is None:
            end_ms = self.last_gaze_timestamp_ms or running_started_ms
        duration = max(0, end_ms - running_started_ms)
        valid_ms = away_ms = 0
        for index, (timestamp, valid, away) in enumerate(self.gaze_observations):
            if index + 1 < len(self.gaze_observations):
                next_timestamp = self.gaze_observations[index + 1][0]
                if not 0 <= next_timestamp - timestamp <= 1000:
                    continue
            else:
                next_timestamp = min(end_ms, timestamp + 1000)
            interval = max(0, min(end_ms, next_timestamp) - max(running_started_ms, timestamp))
            if valid and settings.get("gaze_enabled", True):
                valid_ms += interval
                if away:
                    away_ms += interval
        gaze_status = (
            "disabled"
            if not settings.get("gaze_enabled", True)
            else "unavailable"
            if not valid_ms
            else "observed"
            if away_ms
            else "observed_zero"
        )
        speech_enabled = settings.get("speech_rate_enabled", True)
        filler_enabled = settings.get("filler_words_enabled", True)
        rate = self.average_speech_rate()
        avg_rate = round(rate, 1) if speech_enabled and rate else None
        fillers = dict(self.fillers) if filler_enabled and self.transcript else None
        gaze_metrics = {
            "status": gaze_status,
            "away_count": self.gaze_away_count,
            "away_duration_ms": away_ms,
            "valid_duration_ms": valid_ms,
            "unknown_duration_ms": max(0, duration - valid_ms),
            "coverage_ratio": round(valid_ms / duration, 4) if duration else None,
            "away_ratio": round(away_ms / valid_ms, 4) if valid_ms else None,
        }
        speech_metrics = {
            "status": "disabled"
            if not speech_enabled
            else "observed"
            if avg_rate is not None
            else "unavailable",
            "filler_status": "disabled"
            if not filler_enabled
            else "unavailable"
            if fillers is None
            else "observed"
            if fillers
            else "observed_zero",
            "average_syllables_per_minute": avg_rate,
            "filler_word_counts": fillers,
            "syllable_count": self.syllable_count,
            "voiced_ms": self.voiced_ms,
            "repeat_count": self.repeat_count,
            "warning_episode_count": self.speech_warning_episodes,
        }
        pronunciation_score = self._average(self.pronunciation_scores)
        script_ratio = (
            round(self.script_progress_ratio, 4)
            if settings.get("script") and self.script_alignment_observed
            else None
        )
        average_delta = self._average([float(abs(value)) for value in self.script_pace_deltas])
        return {
            "overall_score": None,
            "gaze_score": None,
            "speech_rate_score": None,
            "filler_word_score": None,
            "gaze_away_count": self.gaze_away_count,
            "gaze_away_duration_ms": away_ms,
            "average_syllables_per_minute": avg_rate,
            "filler_word_counts": fillers,
            "transcript": self.transcript or None,
            "timeline": self.timeline,
            "summary": {
                **self.snapshot(),
                "duration_ms": duration,
                "average_syllables_per_minute": avg_rate,
                "filler_word_counts": fillers,
                "script_completion_ratio": script_ratio,
            },
            "pronunciation_clarity_score": pronunciation_score,
            "script_completion_ratio": script_ratio,
            "time_adherence_score": None,
            "gaze_metrics": gaze_metrics,
            "speech_rate_metrics": speech_metrics,
            "pronunciation_metrics": {
                "sample_count": len(self.pronunciation_scores),
                "average_confidence": self._average(self.pronunciation_confidences),
                "method": "script_agreement",
            },
            "script_sync_metrics": {
                "status": "disabled"
                if not settings.get("script")
                else "observed"
                if self.script_alignment_observed
                else "unavailable",
                "completion_ratio": script_ratio,
                "average_absolute_pace_delta_ms": average_delta,
            },
            "scoring_version": "v2",
        }
