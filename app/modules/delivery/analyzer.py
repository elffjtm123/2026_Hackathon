"""Session-scoped delivery feature aggregation. No raw PCM is retained."""

import itertools
import threading
from collections import Counter
from dataclasses import dataclass, field
from typing import Any

from app.modules.delivery import features
from app.modules.delivery.f0 import SAMPLE_RATE, F0Extractor, parselmouth_f0
from app.modules.delivery.spectral import spectral_balance
from app.modules.speech.segments import CutReason

MIN_REPORT_VOICED_MS = 60_000
WINDOW_BASELINE_EXCLUDE = ("start_ms", "end_ms", "coverage", "observed_ms")


@dataclass(slots=True)
class _Sentence:
    runs: list[tuple[int, int]] = field(default_factory=list)
    rms: list[float] = field(default_factory=list)
    f0: list[float] = field(default_factory=list)
    alpha: list[float] = field(default_factory=list)
    hammarberg: list[float] = field(default_factory=list)
    voiced_ms: int = 0
    syllables: int = 0
    disfluencies: int = 0

    def add_frame(self, start: int, end: int, rms: float) -> None:
        if self.runs and start <= self.runs[-1][1]:
            self.runs[-1] = (self.runs[-1][0], max(end, self.runs[-1][1]))
        else:
            self.runs.append((start, end))
        self.rms.append(rms)
        self.voiced_ms += end - start


@dataclass(slots=True)
class _Window:
    voiced_ms: int = 0
    syllables: float = 0.0
    disfluencies: float = 0.0
    rms: list[float] = field(default_factory=list)
    f0: list[float] = field(default_factory=list)
    alpha: list[float] = field(default_factory=list)
    hammarberg: list[float] = field(default_factory=list)


class DeliveryAnalyzer:
    """Aggregates per-frame and per-utterance observations of one session.

    Contract: every VAD segment must be passed to observe_utterance. Voiced frames that no
    utterance claims are dropped from the window voiced_ms and pauses, and the gap they leave
    is counted as a pause there.
    """

    def __init__(
        self,
        extract_f0: F0Extractor = parselmouth_f0,
        origin_ms: int = 0,
        window_ms: int = 10_000,
    ) -> None:
        self.extract_f0 = extract_f0
        self.origin_ms = origin_ms
        self.window_ms = window_ms
        self.slots: dict[int, _Window] = {}
        self.runs: list[tuple[int, int]] = []
        self.first_ms: int | None = None
        self.last_ms = 0
        self.sentences: dict[int, _Sentence] = {}
        self.pending: list[tuple[int, int, float]] = []
        # observe_frame runs on the event loop while observe_utterance runs in a worker thread.
        self._pending_lock = threading.Lock()
        self.burst_items: list[tuple[int, int, int, int]] = []
        self.voiced_clock = 0
        self.last_sentence_index = 0
        self.last_start_ms = 0
        self.gaps: list[tuple[int, int]] = []

    def mark_gap(self, start_ms: int, end_ms: int) -> None:
        """Declare [start_ms, end_ms) unobserved (a round break): it is no pause, no silent
        window and no speech time. Gaps must not overlap."""
        if end_ms > start_ms:
            self.gaps.append((start_ms, end_ms))

    def _gap_overlap(self, start_ms: int, end_ms: int) -> int:
        return sum(max(0, min(end_ms, b) - max(start_ms, a)) for a, b in self.gaps)

    def _spans_gap(self, left_end: int, right_start: int) -> bool:
        return any(left_end < b and right_start > a for a, b in self.gaps)

    def _pause_stats(self, runs: list[tuple[int, int]]) -> tuple[int, int]:
        """Pause count and longest pause of ordered runs; a pause over a gap is not counted."""
        parts: list[list[tuple[int, int]]] = [[]]
        for run in runs:
            if parts[-1] and self._spans_gap(parts[-1][-1][1], run[0]):
                parts.append([])
            parts[-1].append(run)
        stats = [features.pauses(part) for part in parts]
        return sum(count for count, _ in stats), max((longest for _, longest in stats), default=0)

    def _slot(self, ms: int) -> int:
        return (ms - self.origin_ms) // self.window_ms

    def _window(self, ms: int) -> _Window:
        return self.slots.setdefault(self._slot(ms), _Window())

    def observe_frame(self, start_ms: int, end_ms: int, rms: float, voiced: bool) -> None:
        """Record one frame. A voiced frame only counts once observe_utterance claims it;
        unclaimed voiced frames are dropped from window voiced_ms and pauses (see class doc).
        """
        self.first_ms = start_ms if self.first_ms is None else min(self.first_ms, start_ms)
        self.last_ms = max(self.last_ms, end_ms)
        if voiced:
            with self._pending_lock:
                self.pending.append((start_ms, end_ms, rms))

    def observe_utterance(
        self,
        start_ms: int,
        end_ms: int,
        pcm: bytes,
        cut_reason: CutReason,
        sentence_index: int,
        syllables: int,
        disfluencies: int,
    ) -> None:
        """Utterances must arrive in time order with non-decreasing sentence_index.

        Every VAD segment must be passed here. Voiced frames outside all utterances are dropped
        from window voiced_ms and pauses, and a pause is counted in the gap they leave.
        """
        if sentence_index < self.last_sentence_index:
            raise ValueError("sentence_index must not decrease")
        if start_ms < self.last_start_ms:
            raise ValueError("start_ms must not precede the previous utterance's start_ms")
        self.last_sentence_index = sentence_index
        self.last_start_ms = start_ms
        # Frames are contiguous across a max_length cut, so no gap is inferred there.
        sentence = self.sentences.setdefault(sentence_index, _Sentence())
        before = sentence.voiced_ms
        with self._pending_lock:
            frames = [x for x in self.pending if start_ms <= x[0] < end_ms]
            self.pending = [x for x in self.pending if x[0] >= end_ms]
        slot_ms: Counter[int] = Counter()
        for start, end, rms in frames:
            sentence.add_frame(start, end, rms)
            if self.runs and start <= self.runs[-1][1]:
                self.runs[-1] = (self.runs[-1][0], max(end, self.runs[-1][1]))
            else:
                self.runs.append((start, end))
            window = self._window(start)
            window.voiced_ms += end - start
            window.rms.append(rms)
            slot_ms[self._slot(start)] += end - start
            size = (end - start) * SAMPLE_RATE // 1000 * 2
            first = (start - start_ms) * SAMPLE_RATE // 1000 * 2
            chunk = pcm[first : first + size]
            balance = spectral_balance(chunk) if len(chunk) == size else None
            if balance:
                sentence.alpha.append(balance[0])
                sentence.hammarberg.append(balance[1])
                window.alpha.append(balance[0])
                window.hammarberg.append(balance[1])
        voiced = sentence.voiced_ms - before
        for offset, hz in self.extract_f0(pcm):
            sentence.f0.append(hz)
            self._window(start_ms + offset).f0.append(hz)
        for slot, ms in slot_ms.items():
            window = self.slots[slot]
            window.syllables += syllables * ms / voiced
            window.disfluencies += disfluencies * ms / voiced
        sentence.syllables += syllables
        sentence.disfluencies += disfluencies
        self.burst_items.append(
            (self.voiced_clock + voiced // 2, disfluencies, start_ms, sentence_index)
        )
        self.voiced_clock += voiced

    def _session_f0_median(self) -> float | None:
        """Median over every voiced F0 frame of the session (not a median of medians)."""
        return features.median(
            list(itertools.chain.from_iterable(s.f0 for s in self.sentences.values()))
        )

    def report(self) -> dict[str, Any]:
        session_f0 = self._session_f0_median()
        order = sorted(self.sentences)
        rows = []
        for position, index in enumerate(order):
            s = self.sentences[index]
            count, longest = self._pause_stats(s.runs)
            following = next(
                (self.sentences[i] for i in order[position + 1 :] if self.sentences[i].runs), None
            )
            end_pause = (
                max(0, following.runs[0][0] - s.runs[-1][1])
                if s.runs and following and not self._spans_gap(s.runs[-1][1], following.runs[0][0])
                else None
            )
            rows.append(
                {
                    "sentence_index": index,
                    "voiced_ms": s.voiced_ms,
                    "syllables": s.syllables,
                    "speech_rate": features.speech_rate(
                        s.syllables,
                        s.runs[-1][1]
                        - s.runs[0][0]
                        - self._gap_overlap(s.runs[0][0], s.runs[-1][1])
                        if s.runs
                        else 0,
                    ),
                    "articulation_rate": features.articulation_rate(s.syllables, s.voiced_ms),
                    "pause_count": count,
                    "longest_pause_ms": longest,
                    "sentence_end_pause_ms": end_pause,
                    "disfluency_density": features.disfluency_density(s.disfluencies, s.voiced_ms),
                    "pvq": features.pvq(s.f0),
                    "loudness_dbfs": features.median_dbfs(s.rms),
                    "f0_median_hz": features.median(s.f0),
                    "alpha_ratio_db": features.median(s.alpha),
                    "hammarberg_db": features.median(s.hammarberg),
                }
            )
        baseline = features.baseline(rows)
        for row in rows:
            row["f0_st"] = features.semitones(row["f0_median_hz"], session_f0)
        total = sum(s.voiced_ms for s in self.sentences.values())
        enough = total >= MIN_REPORT_VOICED_MS
        return {
            "status": "observed" if enough else "unavailable",
            "reason": None if enough else "insufficient_voiced_time",
            "total_voiced_ms": total,
            "sentences": rows,
            "baseline": baseline,
            "bursts": features.find_bursts(self.burst_items),
        }

    def windows(self) -> dict[str, Any]:
        """Non-overlapping window_ms slots from the session origin, for arousal analysis.

        Every slot from the first to the last observed frame is emitted, including silent ones.
        Counts of an utterance are split across slots by its voiced ms in each. Windows under
        1000 ms voiced keep voiced_ms, coverage, counts and pause_count; the rest is null.
        Partial windows (session start after origin, session end) are normalised by observed_ms,
        the span between the first and last observed frame inside the window.
        """
        if self.first_ms is None:
            return {"window_ms": self.window_ms, "baseline": {}, "windows": []}
        pause_starts = Counter(
            self._slot(left[1])
            for left, right in itertools.pairwise(self.runs)
            if right[0] - left[1] >= features.PAUSE_MIN_MS
            and not self._spans_gap(left[1], right[0])
        )
        session_f0 = self._session_f0_median()
        rows = []
        for slot in range(self._slot(self.first_ms), self._slot(self.last_ms - 1) + 1):
            w = self.slots.get(slot) or _Window()
            start = self.origin_ms + slot * self.window_ms
            enough = w.voiced_ms >= features.WINDOW_MIN_VOICED_MS
            span = (max(start, self.first_ms), min(start + self.window_ms, self.last_ms))
            observed = span[1] - span[0] - self._gap_overlap(*span)
            if observed <= 0 and not w.voiced_ms and self.gaps:
                continue  # a window inside a gap does not exist

            def acoustic(value: float | None, enough: bool = enough) -> float | None:
                return value if enough else None

            rows.append(
                {
                    "start_ms": start,
                    "end_ms": start + self.window_ms,
                    "voiced_ms": w.voiced_ms,
                    "observed_ms": observed,
                    "coverage": min(1.0, w.voiced_ms / observed) if observed > 0 else None,
                    "syllables": w.syllables,
                    "disfluencies": w.disfluencies,
                    "speech_rate": acoustic(features.speech_rate(w.syllables, observed)),
                    "articulation_rate": acoustic(
                        features.articulation_rate(w.syllables, w.voiced_ms)
                    ),
                    "disfluency_density": acoustic(
                        features.disfluency_density(w.disfluencies, w.voiced_ms)
                    ),
                    "pause_count": pause_starts[slot],
                    "f0_median_hz": acoustic(features.median(w.f0)),
                    "pvq": acoustic(features.pvq(w.f0)),
                    "loudness_dbfs": acoustic(features.median_dbfs(w.rms)),
                    "alpha_ratio_db": acoustic(features.median(w.alpha)),
                    "hammarberg_db": acoustic(features.median(w.hammarberg)),
                }
            )
        baseline = features.baseline(
            rows, features.WINDOW_MIN_VOICED_MS, exclude=WINDOW_BASELINE_EXCLUDE
        )
        for row in rows:
            row["f0_st"] = features.semitones(row["f0_median_hz"], session_f0)
            loudness, reference = row["loudness_dbfs"], baseline.get("loudness_dbfs")
            row["loudness_rel_db"] = (
                loudness - reference if loudness is not None and reference is not None else None
            )
        return {"window_ms": self.window_ms, "baseline": baseline, "windows": rows}
