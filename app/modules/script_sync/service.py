import re
from bisect import bisect_right
from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Any

HANGUL_PATTERN = re.compile(r"[\uac00-\ud7a3]")
TOKEN_PATTERN = re.compile(r"\S+")
SENTENCE_END_PATTERN = re.compile(r"[.!?。！？]+$")
CLAUSE_END_PATTERN = re.compile(r"[,;:，；：]+$")


def _alignment_text(text: str) -> str:
    return re.sub(r"[^0-9a-z가-힣]", "", text.lower())


def normalize_script(text: str) -> str:
    return " ".join(text.strip().split())


def count_korean_syllables(text: str) -> int:
    return len(HANGUL_PATTERN.findall(text))


def _spoken_units(text: str) -> int:
    syllables = count_korean_syllables(text)
    return syllables or len(re.sub(r"[^\w]", "", text, flags=re.UNICODE))


@dataclass(frozen=True, slots=True)
class ScriptPlan:
    normalized_script: str
    syllable_count: int
    target_syllables_per_minute: float
    estimated_duration_seconds: int
    timeline: list[dict[str, Any]]
    warnings: list[str]

    def as_dict(self) -> dict[str, Any]:
        return {
            "normalized_script": self.normalized_script,
            "syllable_count": self.syllable_count,
            "target_syllables_per_minute": self.target_syllables_per_minute,
            "estimated_duration_seconds": self.estimated_duration_seconds,
            "timeline": self.timeline,
            "warnings": self.warnings,
        }


def analyze_script(script: str, time_limit_seconds: int) -> ScriptPlan:
    normalized = normalize_script(script)
    tokens = TOKEN_PATTERN.findall(normalized)
    syllable_count = _spoken_units(normalized)
    target_spm = syllable_count * 60 / time_limit_seconds

    weights: list[float] = []
    for token in tokens:
        weight = float(max(1, _spoken_units(token)))
        if SENTENCE_END_PATTERN.search(token):
            weight += 4
        elif CLAUSE_END_PATTERN.search(token):
            weight += 2
        weights.append(float(weight))

    total_weight = sum(weights) or 1.0
    cursor_ms = 0
    sentence_index = 0
    timeline: list[dict[str, Any]] = []
    for index, (token, weight) in enumerate(zip(tokens, weights, strict=True)):
        duration_ms = round(time_limit_seconds * 1000 * weight / total_weight)
        end_ms = time_limit_seconds * 1000 if index == len(tokens) - 1 else cursor_ms + duration_ms
        timeline.append(
            {
                "token_index": index,
                "sentence_index": sentence_index,
                "text": token,
                "target_start_ms": cursor_ms,
                "target_end_ms": end_ms,
            }
        )
        cursor_ms = end_ms
        if SENTENCE_END_PATTERN.search(token):
            sentence_index += 1

    warnings: list[str] = []
    if target_spm < 120:
        warnings.append("제한시간에 비해 대본이 짧아 긴 침묵이 생길 수 있습니다.")
    elif target_spm > 420:
        warnings.append("제한시간에 비해 대본이 길어 목표 발화 속도가 비현실적입니다.")
    estimated_duration = round(syllable_count / 300 * 60) if syllable_count else 0
    return ScriptPlan(
        normalized,
        syllable_count,
        round(target_spm, 1),
        estimated_duration,
        timeline,
        warnings,
    )


class ScriptSyncService:
    """Monotonic local alignment for partial/final transcripts."""

    def __init__(self, plan: ScriptPlan) -> None:
        self.plan = plan
        self.cursor = -1
        self.confirmed_cursor = -1
        self.tokens = [_alignment_text(str(item["text"])) for item in plan.timeline]
        self.text = "".join(self.tokens)
        self.ends: list[int] = []
        offset = 0
        for token in self.tokens:
            offset += len(token)
            self.ends.append(offset)

    def update(self, transcript: str, timestamp_ms: int, *, is_final: bool) -> dict[str, Any]:
        text = _alignment_text(transcript)
        tokens = self.tokens
        candidates: list[tuple[float, int, int]] = []
        if is_final and len(text) >= 4:
            start = max(0, self.confirmed_cursor - 3)
            offset = self.ends[start - 1] if start else 0
            exact = self.text.find(text, offset)
            if exact >= 0:
                if self.text.find(text, exact + 1) < 0:
                    candidates.append(
                        (
                            1.0,
                            bisect_right(self.ends, exact),
                            bisect_right(self.ends, exact + len(text) - 1),
                        )
                    )
                # Repeated exact phrases remain ambiguous, even outside the local window.
            else:
                for left in range(start, min(len(tokens), start + 40)):
                    joined = ""
                    # Bound by transcript length, not a fixed 40-token end position.
                    for right in range(left, len(tokens)):
                        joined += tokens[right]
                        if len(joined) > len(text) * 1.6:
                            break
                        if len(joined) >= len(text) * 0.6:
                            score = SequenceMatcher(None, text, joined, autojunk=False).ratio()
                            candidates.append((score, left, right))
        candidates.sort(reverse=True)
        best = candidates[0] if candidates else (0.0, 0, 0)
        # Alternate lengths of the same span are not independent competing matches.
        runner_up = max(
            (score for score, left, right in candidates if right < best[1] or left > best[2]),
            default=0.0,
        )
        matched = best[0] >= 0.65 and best[0] - runner_up >= 0.10
        if matched:
            self.cursor = self.confirmed_cursor = max(self.confirmed_cursor, best[2])
        return {
            **self._progress(timestamp_ms, self.cursor),
            "alignment_status": "matched" if matched else "uncertain",
            "match_score": round(best[0], 4),
            "matched_start_token": best[1] if matched else None,
            "matched_end_token": best[2] if matched else None,
        }

    def _progress(self, timestamp_ms: int, cursor: int) -> dict[str, Any]:
        timeline = self.plan.timeline
        expected = 0
        for item in timeline:
            if int(item["target_start_ms"]) <= timestamp_ms:
                expected = int(item["token_index"])
            else:
                break
        current_target = int(timeline[cursor]["target_end_ms"]) if cursor >= 0 else None
        pace_delta = current_target - timestamp_ms if current_target is not None else None
        status = "unknown" if pace_delta is None else "on_time"
        if pace_delta is not None and pace_delta > 3_000:
            status = "ahead"
        elif pace_delta is not None and pace_delta < -3_000:
            status = "behind"
        next_index = min(cursor + 1, max(len(timeline) - 1, 0))
        return {
            "current_token_index": cursor if cursor >= 0 else None,
            "current_sentence_index": int(timeline[cursor]["sentence_index"])
            if cursor >= 0
            else None,
            "expected_token_index": expected,
            "progress_ratio": round((cursor + 1) / max(len(timeline), 1), 4),
            "expected_progress_ratio": round((expected + 1) / max(len(timeline), 1), 4),
            "pace_delta_ms": pace_delta,
            "pace_status": status,
            "active_text": str(timeline[cursor]["text"]) if cursor >= 0 else "",
            "next_text": str(timeline[next_index]["text"]) if timeline else "",
        }
