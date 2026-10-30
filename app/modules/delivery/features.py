"""Rule-free feature math for delivery analysis."""

import math
import statistics
from collections.abc import Sequence
from typing import Any

PAUSE_MIN_MS = 250
BURST_WINDOW_MS = 10_000
BURST_MIN_COUNT = 3
BASELINE_MIN_VOICED_MS = 3000
WINDOW_MIN_VOICED_MS = 1000


def articulation_rate(syllables: float, voiced_ms: int) -> float | None:
    return syllables * 60_000 / voiced_ms if voiced_ms > 0 else None


def speech_rate(syllables: float, span_ms: float) -> float | None:
    """Syllables per minute over a time span, pauses included."""
    return syllables * 60_000 / span_ms if span_ms > 0 else None


def semitones(hz: float | None, reference_hz: float | None) -> float | None:
    if not hz or not reference_hz:
        return None
    return 12 * math.log2(hz / reference_hz)


def median(values: Sequence[float]) -> float | None:
    return statistics.median(values) if values else None


def disfluency_density(count: float, voiced_ms: int) -> float | None:
    return count * 60_000 / voiced_ms if voiced_ms > 0 else None


def median_dbfs(rms_values: Sequence[float]) -> float | None:
    if not rms_values:
        return None
    return 20 * math.log10(max(statistics.median(rms_values), 1e-6))


def pvq(f0: Sequence[float]) -> float | None:
    if len(f0) < 2:
        return None
    mean = statistics.fmean(f0)
    return statistics.pstdev(f0) / mean if mean > 0 else None


def pauses(runs: Sequence[tuple[int, int]]) -> tuple[int, int]:
    """Count and longest of unvoiced gaps >= 250 ms between ordered voiced runs."""
    gaps = [right[0] - left[1] for left, right in zip(runs, runs[1:], strict=False)]
    long = [gap for gap in gaps if gap >= PAUSE_MIN_MS]
    return len(long), max(long, default=0)


def find_bursts(items: Sequence[tuple[int, int, int, int]]) -> list[dict[str, int]]:
    """items: (voiced clock ms, disfluencies, utterance start ms, sentence index)."""
    bursts: list[dict[str, int]] = []
    window: list[tuple[int, int]] = []
    for clock, count, time_ms, sentence in items:
        if not count:
            continue
        window = [x for x in window if clock - x[0] <= BURST_WINDOW_MS]
        window.append((clock, count))
        total = sum(c for _, c in window)
        if total >= BURST_MIN_COUNT:
            bursts.append({"time_ms": time_ms, "sentence_index": sentence, "count": total})
            window = []
    return bursts


def baseline(
    rows: Sequence[dict[str, Any]],
    min_voiced_ms: int = BASELINE_MIN_VOICED_MS,
    exclude: Sequence[str] = ("sentence_index",),
) -> dict[str, float]:
    """Median of every numeric field over rows with at least min_voiced_ms of voiced time."""
    eligible = [x for x in rows if x["voiced_ms"] >= min_voiced_ms]
    result: dict[str, float] = {}
    for key in eligible[0] if eligible else ():
        if key in exclude:
            continue
        values = [x[key] for x in eligible if x[key] is not None]
        if values:
            result[key] = statistics.median(values)
    return result
