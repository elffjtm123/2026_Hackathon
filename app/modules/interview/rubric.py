"""Rubric data (draft), evaluability checks and score conversion."""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import Literal

from app.modules.interview.questions import ItemRecord, RubricItem

NotEvaluableReason = Literal["no_response", "too_short", "recognition_failed"]

# Evaluability thresholds (tune by demo experiments, plan stage 7).
MIN_HANGUL_SYLLABLES = 20
# Recognition failure: at least this much voiced time but fewer syllables per voiced second
# than the minimum below.
RECOGNITION_MIN_VOICED_MS = 5000
RECOGNITION_MIN_SYLLABLES_PER_SECOND = 1.0

MAX_GRADE = 4

# Grades describe how much of the expected behaviour was observed (NCS five levels).
GRADE_DEFINITIONS: dict[int, str] = {
    4: "기대행동이 답변에서 완벽하게 관찰된다",
    3: "기대행동이 상당히 관찰된다",
    2: "기대행동이 약간 관찰된다",
    1: "기대행동이 거의 관찰되지 않는다",
    0: "기대행동이 전혀 관찰되지 않는다",
}


@dataclass(frozen=True)
class RubricCriteria:
    item: RubricItem
    label: str
    observe: str  # what to check in the answer
    low: str  # 낮은 수준: 확인·인식
    mid: str  # 중간: 분석·공유
    high: str  # 높은 수준: 종합·최적 선택·적용


RUBRIC: dict[RubricItem, RubricCriteria] = {
    RubricItem.UNDERSTANDING: RubricCriteria(
        RubricItem.UNDERSTANDING,
        "질문·직무 이해",
        "질문의 핵심과 직무·기술 개념을 적절하게 이해했는지",
        "질문의 주제를 알아차리고 관련된 내용을 말한다.",
        "질문이 묻는 핵심을 짚고 직무나 개념과 연결해 설명한다.",
        "질문의 의도와 직무 맥락을 함께 고려해 요점에 맞게 답을 구성한다.",
    ),
    RubricItem.REASONING: RubricCriteria(
        RubricItem.REASONING,
        "문제 해결과 판단 근거",
        "문제와 제약, 대안 및 선택 이유를 설명했는지",
        "문제 상황이나 선택한 방법을 말한다.",
        "제약과 대안을 구분하고 선택의 이유를 설명한다.",
        "대안을 비교해 가장 알맞은 방법을 고른 근거와 감수한 단점까지 설명한다.",
    ),
    RubricItem.SPECIFICITY: RubricCriteria(
        RubricItem.SPECIFICITY,
        "경험·행동의 구체성",
        "실제 사례와 본인의 역할·행동이 구체적인지",
        "경험이 있었다는 사실과 대략의 상황을 말한다.",
        "시점·장면·숫자 등으로 사례를 특정하고 본인이 맡은 역할을 말한다.",
        "본인이 직접 한 행동을 순서대로 구체적으로 설명하고 팀의 몫과 구분한다.",
    ),
    RubricItem.LEARNING: RubricCriteria(
        RubricItem.LEARNING,
        "결과와 학습",
        "배운 점과 그것을 배우게 된 계기를 본인 역할과 연결해 설명했는지, 결과를 어떻게 확인했는지",
        "결과나 느낀 점을 일반적인 표현으로 말한다.",
        "본인 역할에서 생긴 문제와 거기서 배운 내용을 말한다.",
        "배운 점이 구체적이고 계기와 연결되며, 이후 행동이 달라진 점과 결과 확인 방법까지 말한다."
        " 결과가 좋았다는 말만으로는 높은 등급을 주지 않는다.",
    ),
    RubricItem.COLLABORATION: RubricCriteria(
        RubricItem.COLLABORATION,
        "협업과 의사소통",
        "타인의 의견을 반영하고 조율한 과정을 설명했는지",
        "함께 일한 사람이 있었다는 것을 말한다.",
        "상대의 의견이나 입장을 파악하고 공유한 과정을 설명한다.",
        "의견 차이를 조율해 합의에 이르거나 상대에 맞게 소통 방식을 바꾼 과정을 설명한다.",
    ),
}

_HANGUL = re.compile(r"[가-힣]")


def count_hangul_syllables(text: str) -> int:
    return len(_HANGUL.findall(text))


def assess_evaluability(item: ItemRecord) -> NotEvaluableReason | None:
    """Return why the answer cannot be graded, or None if it can."""
    if item.advance_reason == "no_response" or not item.utterances:
        return "no_response"
    syllables = count_hangul_syllables(item.transcript)
    voiced_ms = sum(u.voiced_ms for u in item.utterances)
    if (
        voiced_ms >= RECOGNITION_MIN_VOICED_MS
        and syllables / (voiced_ms / 1000) < RECOGNITION_MIN_SYLLABLES_PER_SECOND
    ):
        return "recognition_failed"
    if syllables < MIN_HANGUL_SYLLABLES:
        return "too_short"
    return None


@dataclass(frozen=True)
class ScoreResult:
    score: float  # 0-20
    excluded_items: tuple[RubricItem, ...] = field(default=())  # applicable but ungraded

    @property
    def partial(self) -> bool:
        """True when some applicable items were left out (show as "부분 평가")."""
        return bool(self.excluded_items)


def score(grades: Mapping[RubricItem, int], applicable_items: Iterable[RubricItem]) -> ScoreResult:
    """Question score 0-20: 20 * sum(grades) / (4 * graded applicable items).

    Applicable items without a grade (invalidated, e.g. the evidence quote is not in the
    answer) are dropped from both the sum and the denominator and listed in
    `excluded_items`, so the caller can mark the question as partially evaluated.
    Raises ValueError for grades outside 0-4 or when no applicable item has a grade.
    """
    applicable = list(applicable_items)
    used = [item for item in applicable if item in grades]
    if not used:
        raise ValueError("no graded applicable items")
    for item in used:
        if not 0 <= grades[item] <= MAX_GRADE:
            raise ValueError(f"grade out of range for {item.value}: {grades[item]}")
    value = 20 * sum(grades[item] for item in used) / (MAX_GRADE * len(used))
    excluded = tuple(item for item in applicable if item not in grades)
    return ScoreResult(value, excluded)


def overall(scores: Iterable[float | None]) -> float | None:
    """Mean of scored questions; not-evaluable and unscored (None) are excluded."""
    values = [s for s in scores if s is not None]
    return sum(values) / len(values) if values else None
