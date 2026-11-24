"""Gap types, rule signals, fixed fallback questions and selection for follow-up questions."""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass
from enum import Enum

from app.modules.interview.questions import SITUATIONAL, ItemRecord, PlannedQuestion, RubricItem
from app.modules.interview.rubric import assess_evaluability


class GapType(str, Enum):
    OWN_ROLE = "own_role"
    REASONING = "reasoning"
    RESULT_CHECK = "result_check"
    LEARNING = "learning"
    COLLABORATION = "collaboration"
    CONCRETE_EXAMPLE = "concrete_example"
    EXPECTED_RESULT = "expected_result"
    CORE_TASK = "core_task"
    STAKEHOLDERS = "stakeholders"


# Priority for project/experience questions (plan section 4.3).
_EXPERIENCE_ORDER = [
    GapType.OWN_ROLE,
    GapType.LEARNING,
    GapType.REASONING,
    GapType.CONCRETE_EXAMPLE,
    GapType.COLLABORATION,
    GapType.RESULT_CHECK,
]
# Situational questions are hypothetical: no result_check / learning; NCS situational set added.
_SITUATIONAL_ORDER = [
    GapType.CORE_TASK,
    GapType.STAKEHOLDERS,
    GapType.REASONING,
    GapType.EXPECTED_RESULT,
    GapType.COLLABORATION,
    GapType.CONCRETE_EXAMPLE,
    GapType.OWN_ROLE,
]

_FALLBACK_TEXT = {
    GapType.OWN_ROLE: "그중 본인이 직접 맡은 부분은 무엇이었나요?",
    GapType.REASONING: "그 방법을 고른 이유는 무엇인가요?",
    GapType.RESULT_CHECK: "그 결과는 어떻게 확인했나요?",
    GapType.LEARNING: "그 경험 이후 어떤 점이 달라졌나요?",
    GapType.COLLABORATION: "의견이 달랐던 팀원과는 어떻게 조율했나요?",
    GapType.CONCRETE_EXAMPLE: "방금 말한 내용을 실제 사례 하나로 설명해 주세요.",
    GapType.EXPECTED_RESULT: "그렇게 하면 어떤 결과가 나올 것으로 예상하나요?",
    GapType.CORE_TASK: "이 상황의 핵심 과제는 무엇이라고 보나요?",
    GapType.STAKEHOLDERS: "먼저 고려해야 할 사람은 누구인가요?",
}

# Rubric item each gap belongs to (plan section 4.3); a gap is only allowed when the question
# is graded on that item.
GAP_RUBRIC_ITEM = {
    GapType.OWN_ROLE: RubricItem.SPECIFICITY,
    GapType.CONCRETE_EXAMPLE: RubricItem.SPECIFICITY,
    GapType.REASONING: RubricItem.REASONING,
    GapType.EXPECTED_RESULT: RubricItem.REASONING,
    GapType.CORE_TASK: RubricItem.UNDERSTANDING,
    GapType.RESULT_CHECK: RubricItem.LEARNING,
    GapType.LEARNING: RubricItem.LEARNING,
    GapType.COLLABORATION: RubricItem.COLLABORATION,
    GapType.STAKEHOLDERS: RubricItem.COLLABORATION,
}

# First-person words are matched at a word start so "문제가", "과제가", "안내가" do not count.
_WE = re.compile(r"(?<![가-힣])(?:우리|저희)")
_I = re.compile(r"(?<![가-힣])(?:제가|저는|내가)")


def allowed_gaps(question: PlannedQuestion) -> list[GapType]:
    """Gaps this question may be followed up on, in priority order.

    Limited to gaps whose rubric item is one of the question's `rubric_items`.
    """
    order = _SITUATIONAL_ORDER if question.subtype == SITUATIONAL else _EXPERIENCE_ORDER
    return [gap for gap in order if GAP_RUBRIC_ITEM[gap] in question.rubric_items]


def we_only(text: str) -> bool:
    """Rule signal: the answer says 우리/저희 but never 제가/저는/내가."""
    return bool(_WE.search(text)) and not _I.search(text)


def detect_rule_gaps(item: ItemRecord) -> list[GapType]:
    """Gaps found by string rules alone (the LLM adds the rest)."""
    gaps: list[GapType] = []
    if we_only(item.transcript):
        gaps.append(GapType.OWN_ROLE)
    allowed = set(allowed_gaps(item.question))
    return [gap for gap in gaps if gap in allowed]


@dataclass
class FollowUpCandidate:
    parent_id: str
    gaps: list[GapType]  # allowed gaps only, highest priority first

    @property
    def top_gap(self) -> GapType:
        return self.gaps[0]


def follow_up_candidate(item: ItemRecord, gaps: Iterable[GapType]) -> FollowUpCandidate | None:
    """Candidate for one answered main question, or None when no follow-up is allowed.

    Never for follow-up questions, unscored questions (empty rubric_items, e.g. 마무리) or
    answers that are not evaluable.
    """
    question = item.question
    if question.kind == "follow_up" or not question.rubric_items:
        return None
    if assess_evaluability(item) is not None:
        return None
    found = set(gaps)
    ordered = [gap for gap in allowed_gaps(question) if gap in found]
    if not ordered:
        return None
    return FollowUpCandidate(parent_id=question.id, gaps=ordered)


def select_follow_ups(
    candidates: list[FollowUpCandidate], max_count: int
) -> list[FollowUpCandidate]:
    """Pick up to `max_count` candidates with the most gaps (ties keep input order)."""
    if max_count <= 0:
        return []
    ranked = sorted(enumerate(candidates), key=lambda pair: (-len(pair[1].gaps), pair[0]))
    return [candidate for _, candidate in ranked[:max_count]]


def fallback_question_text(gap: GapType) -> str:
    return _FALLBACK_TEXT[gap]


def build_fallback_follow_up(parent: PlannedQuestion, gap: GapType) -> PlannedQuestion:
    """Fixed-text follow-up used when LLM generation fails or fails validation."""
    return PlannedQuestion(
        id=f"{parent.id}-f",
        kind="follow_up",
        subtype=gap.value,
        text=fallback_question_text(gap),
        intent=f"답변에서 빠진 요소({gap.value})를 확인한다.",
        source_quote=None,
        rubric_items=list(parent.rubric_items),
        parent_id=parent.id,
        bank_id=None,
        round=2,
    )
