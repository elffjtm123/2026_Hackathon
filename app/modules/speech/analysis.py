"""One Korean syllable-rate and transcript-derived filler implementation."""

import re
from collections import Counter, deque
from dataclasses import asdict, dataclass
from typing import Any, Literal

from app.modules.speech.segments import FinalUtterance

Pace = Literal["unknown", "slow", "normal", "fast"]
_FILLERS = (
    "어",
    "음",
    "아",
    "에",
    "으",
    "응",
    "흠",
    "뭐",
    "좀",
    "막",
    "약간",
    "그냥",
    "이제",
    "인제",
    "저기",
    "그",
    "일단",
    "사실",
    "뭔가",
    "아무튼",
    "어쨌든",
    "뭐냐",
    "자",
    "그러니까",
    "그니까",
    "그러니까요",
    "사실은",
    "기본적으로",
    "솔직히",
    "말하자면",
    "뭐랄까",
    "어떻게 보면",
    "있잖아요",
    "있잖아",
    "그래가지고",
    "다시 말해서",
    "솔직히 말해서",
    "어떻게 말하면",
    "그렇게 말하자면",
    "그러다 보니까",
    "뭔가 좀",
)
_FILLER_PATTERN = re.compile(
    r"(?<!\w)(?:"
    + "|".join(
        re.escape(word).replace(r"\ ", r"\s+") + ("+" if len(word) == 1 else "")
        for word in sorted(_FILLERS, key=len, reverse=True)
    )
    + r")(?!\w)"
)


@dataclass(frozen=True, slots=True)
class SpeechMetrics:
    syllable_count: int
    voiced_ms: int
    elapsed_ms: int
    syllables_per_minute: float | None
    pace: Pace
    filler_counts: dict[str, int]
    repeat_count: int

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def pace_for_rate(rate: float | None) -> Pace:
    if rate is None:
        return "unknown"
    return "slow" if rate < 140 else "fast" if rate > 360 else "normal"


def filler_counts(text: str) -> tuple[dict[str, int], int]:
    cleaned = re.sub(r"[^\w\s]", " ", text)
    tokens = cleaned.split()
    # ponytail: lexical candidates, not an acoustic disfluency diagnosis; STT may omit them.
    counts: Counter[str] = Counter()
    for match in _FILLER_PATTERN.findall(cleaned):
        word = " ".join(match.split())
        if len(set(word)) == 1 and word[0] in _FILLERS:
            word = word[0]
        counts[word] += 1
    repeats = sum(left == right for left, right in zip(tokens, tokens[1:], strict=False))
    return dict(counts), repeats


def analyze_utterance(
    final: FinalUtterance,
    *,
    rate_enabled: bool = True,
    fillers_enabled: bool = True,
) -> SpeechMetrics:
    count = len(re.findall(r"[가-힣]", final.text)) if rate_enabled else 0
    voiced = max(0, final.voiced_ms)
    rate = round(count * 60_000 / voiced, 1) if count and voiced else None
    fillers, repeats = filler_counts(final.text) if fillers_enabled else ({}, 0)
    return SpeechMetrics(
        count,
        voiced,
        max(0, final.end_ms - final.start_ms),
        rate,
        pace_for_rate(rate),
        fillers,
        repeats,
    )


class SpeechRateWindow:
    def __init__(self) -> None:
        self.items: deque[tuple[FinalUtterance, SpeechMetrics]] = deque()

    def add(self, final: FinalUtterance, metrics: SpeechMetrics) -> None:
        if metrics.syllable_count and metrics.voiced_ms:
            self.items.append((final, metrics))

    def snapshot(self, now_ms: int) -> SpeechMetrics:
        while self.items and self.items[0][0].end_ms <= now_ms - 10_000:
            self.items.popleft()
        # ponytail: whole finals by end time; word timestamps needed for exact window clipping.
        count = sum(x.syllable_count for _, x in self.items)
        voiced = sum(x.voiced_ms for _, x in self.items)
        rate = round(count * 60_000 / voiced, 1) if count >= 10 and voiced >= 2000 else None
        return SpeechMetrics(count, voiced, 10_000, rate, pace_for_rate(rate), {}, 0)


def pace_message(pace: Pace, rate: float | None) -> str:
    if pace == "unknown":
        return "발화 속도를 판단할 충분한 음성이 아직 없습니다."
    state = {"slow": "느립니다", "normal": "설정 범위 안입니다", "fast": "빠릅니다"}[pace]
    return f"최근 발화 속도가 {state} (분당 {rate:g}음절)."
