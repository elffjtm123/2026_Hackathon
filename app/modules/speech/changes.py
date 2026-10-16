"""Internal-only input-level and syllable-rate changes; no feedback or emotion labels."""

import math
from collections import deque
from dataclasses import dataclass
from statistics import median
from typing import Literal


@dataclass
class SpeechChange:
    kind: Literal["volume", "pace"]
    direction: Literal["up", "down"]
    start_ms: int
    end_ms: int
    baseline: float
    value: float
    unit: str


class _Trend:
    def __init__(self, kind: Literal["volume", "pace"], events: deque[SpeechChange]) -> None:
        self.kind, self.events = kind, events
        self.history: deque[tuple[int, float, int]] = deque(maxlen=60)
        self.pending: SpeechChange | None = None
        self.active: SpeechChange | None = None
        self.pending_ms = 0
        self.last_end_ms = -1

    def interrupt(self) -> None:
        self.pending = self.active = None
        self.pending_ms = 0

    def add(self, start: int, end: int, value: float, voiced_ms: int) -> None:
        if start < self.last_end_ms:
            return
        if start - self.last_end_ms > 1000:
            self.interrupt()
        self.last_end_ms = end
        while self.history and self.history[0][0] <= start - 30000:
            self.history.popleft()
        required_ms, required_items = (3000, 6) if self.kind == "volume" else (6000, 3)
        if len(self.history) >= required_items and sum(x[2] for x in self.history) >= required_ms:
            previous = self.active or self.pending
            baseline = self.pending.baseline if self.pending else median(x[1] for x in self.history)
            delta = value - baseline if self.kind == "volume" else value / baseline - 1
            threshold = 6 if self.kind == "volume" else 0.25
            direction: Literal["up", "down"] = "up" if delta > 0 else "down"
            if abs(delta) >= threshold:
                if previous is None or previous.direction != direction:
                    self.interrupt()
                    self.pending = SpeechChange(
                        self.kind,
                        direction,
                        start,
                        end,
                        baseline,
                        value,
                        "dBFS" if self.kind == "volume" else "syllables/min",
                    )
                current = self.active or self.pending
                assert current is not None
                current.end_ms, current.value = end, value
                self.pending_ms += voiced_ms
                if self.active is None and self.pending_ms >= (
                    1000 if self.kind == "volume" else 2000
                ):
                    self.active, self.pending = current, None
                    self.events.append(current)
            else:
                self.interrupt()
        else:
            self.interrupt()
        self.history.append((end, value, voiced_ms))


class SpeechChangeDetector:
    def __init__(self) -> None:
        # shortcut: provisional thresholds; validate on real microphones before showing feedback.
        self.events: deque[SpeechChange] = deque(maxlen=256)
        self._volume = _Trend("volume", self.events)
        self._pace = _Trend("pace", self.events)
        self._bucket_start: int | None = None
        self._last_audio_end = -1
        self._energy = 0.0
        self._voiced_ms = 0

    def observe_audio(self, start_ms: int, end_ms: int, rms: float, voiced: bool) -> None:
        if end_ms <= start_ms or start_ms < self._last_audio_end or not math.isfinite(rms):
            return
        if not 0 <= rms <= 1:
            return
        if self._bucket_start is None or start_ms > self._last_audio_end:
            self._bucket_start, self._energy, self._voiced_ms = start_ms, 0.0, 0
            self._volume.interrupt()
        self._last_audio_end = end_ms
        cursor = start_ms
        while cursor < end_ms:
            boundary = self._bucket_start + 500
            stop = min(end_ms, boundary)
            if voiced and rms > 0:
                self._energy += rms * rms * (stop - cursor)
                self._voiced_ms += stop - cursor
            cursor = stop
            if stop == boundary:
                if self._voiced_ms >= 300:
                    dbfs = 10 * math.log10(self._energy / self._voiced_ms)
                    self._volume.add(self._bucket_start, boundary, dbfs, self._voiced_ms)
                else:
                    self._volume.interrupt()
                self._bucket_start, self._energy, self._voiced_ms = boundary, 0.0, 0

    def observe_pace(self, start_ms: int, end_ms: int, syllables: int, voiced_ms: int) -> None:
        if start_ms < 0 or end_ms <= start_ms or voiced_ms > end_ms - start_ms:
            return
        if syllables < 4 or voiced_ms < 1000:
            self._pace.interrupt()
            return
        self._pace.add(start_ms, end_ms, syllables * 60000 / voiced_ms, voiced_ms)
