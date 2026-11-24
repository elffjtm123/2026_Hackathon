"""Question and material types plus validation of generated questions and materials."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Literal

QuestionKind = Literal["common", "document", "follow_up"]
AdvanceReason = Literal["silence", "time_limit", "no_response", "stopped"]
MaterialKind = Literal["project", "skill", "activity"]


class RubricItem(str, Enum):
    """The five equal-weight evaluation items (plan section 5)."""

    UNDERSTANDING = "understanding"  # 질문·직무 이해
    REASONING = "reasoning"  # 문제 해결과 판단 근거
    SPECIFICITY = "specificity"  # 경험·행동의 구체성
    LEARNING = "learning"  # 결과와 학습
    COLLABORATION = "collaboration"  # 협업과 의사소통


class CommonCategory(str, Enum):
    """Common-question categories; the value doubles as `PlannedQuestion.subtype`."""

    SELF_INTRODUCTION = "self_introduction"
    MOTIVATION = "motivation"
    STRENGTH_WEAKNESS = "strength_weakness"
    FUTURE_PLAN = "future_plan"
    CLOSING = "closing"
    PERSONALITY_BEHAVIORAL = "personality_behavioral"
    PERSONALITY_SITUATIONAL = "personality_situational"


SELF_INTRODUCTION = CommonCategory.SELF_INTRODUCTION.value
SITUATIONAL = CommonCategory.PERSONALITY_SITUATIONAL.value
# Subtypes of document-based questions (kind == "document").
JOB = "job"
EXPERIENCE = "experience"


@dataclass
class PlannedQuestion:
    id: str
    kind: QuestionKind
    subtype: str
    text: str
    intent: str = ""
    source_quote: str | None = None
    rubric_items: list[RubricItem] = field(default_factory=list)  # empty = not evaluated
    parent_id: str | None = None
    bank_id: str | None = None
    round: Literal[1, 2] = 1


@dataclass
class Material:
    kind: MaterialKind
    quote: str
    summary: str = ""


@dataclass
class FinalUtterance:
    utterance_id: str
    start_ms: int
    end_ms: int
    text: str
    voiced_ms: int


@dataclass
class ItemRecord:
    question: PlannedQuestion
    shown_ms: int
    answer_started_ms: int | None
    ended_ms: int
    advance_reason: AdvanceReason
    replay_used: bool
    utterances: list[FinalUtterance]
    transcript: str


# ---------------------------------------------------------------- validation

MAX_QUESTION_CHARS = 100
MAX_SITUATIONAL_CHARS = 200
# Bigram Jaccard at or above this counts as the same question (tune by experiment).
SIMILARITY_THRESHOLD = 0.6
NGRAM_SIZE = 2

# Keyword-based filter for topics unrelated to the job (plan section 4.0). Patterns are
# anchored so job-relevant text is not flagged: "연세대학교", "시절에", "매출 신장", "API 키가",
# "부동산 시세", "부모 노드", "나이브 베이즈" and "개발자로서의 성장 과정" pass.
_BANNED_PATTERNS: dict[str, re.Pattern[str]] = {
    "family_background": re.compile(
        r"가족(?!\s?같)|부모님|부모(?:의|가|는)?\s?(?:직업|학력|재산|직장)|아버지|어머니|아버님"
        r"|어머님|형제(?!\s?노드)|자매|자녀|가정\s?환경|집안|성장\s?배경|(?:어린|유년)\s?시절"
        r"|(?:가정|가족|부모)[^.?]{0,10}성장\s?과정"
    ),
    "age": re.compile(r"나이(?!브|트)|몇\s?살|연세(?:가|는|를)|생년월일|몇\s?년생|\d{2,4}\s?년생"),
    "marital": re.compile(r"결혼|혼인|미혼|기혼|배우자|출산|임신|남자\s?친구|여자\s?친구|애인"),
    "origin": re.compile(
        r"출신\s?지역|출신지|고향|어디(?:에|에서)?\s?(?:사세요|사시|사는|살고|살아)|거주지|어느\s?지역"
    ),
    "religion": re.compile(r"종교|교회|성당|사찰"),
    "appearance": re.compile(r"외모|신체\s?조건|몸무게|체중|키가\s?(?:몇|크|작)|키는\s?몇"),
    "property": re.compile(r"재산|자산\s?규모|집안\s?형편|부동산\s?(?:보유|소유)"),
}


def normalize_whitespace(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def find_banned_topic(text: str) -> str | None:
    """Return the banned-topic label found in `text`, or None."""
    for label, pattern in _BANNED_PATTERNS.items():
        if pattern.search(text):
            return label
    return None


def is_double_question(text: str) -> bool:
    """Heuristic: two or more question marks mean the text asks two things.

    A "~와 ~에 대해 말씀해 주세요" pattern alone is not flagged because it also matches
    harmless noun phrases ("팀원과 갈등에 대해"); only the question-mark count is used.
    Known gap: a single question mark asking two things ("A와 B는 무엇인가요?") is not caught.
    """
    return len(re.findall(r"[?？]", text)) >= 2


def validate_material(material: Material, document_text: str) -> str | None:
    """Return a rejection reason, or None when the material may be used."""
    quote = normalize_whitespace(material.quote)
    if not quote:
        return "empty_quote"
    if quote not in normalize_whitespace(document_text):
        return "quote_not_in_document"
    if find_banned_topic(material.quote) or find_banned_topic(material.summary):
        return "banned_topic"
    return None


def validate_question(question: PlannedQuestion) -> str | None:
    """Return a rejection reason (empty, too_long, banned_topic, double_question) or None."""
    text = question.text.strip()
    if not text:
        return "empty"
    limit = MAX_SITUATIONAL_CHARS if question.subtype == SITUATIONAL else MAX_QUESTION_CHARS
    if len(text) > limit:
        return "too_long"
    if find_banned_topic(text):
        return "banned_topic"
    if is_double_question(text):
        return "double_question"
    return None


def _ngrams(text: str) -> set[str]:
    compact = re.sub(r"\s+", "", text)
    if len(compact) < NGRAM_SIZE:
        return {compact} if compact else set()
    return {compact[i : i + NGRAM_SIZE] for i in range(len(compact) - NGRAM_SIZE + 1)}


def text_similarity(a: str, b: str) -> float:
    grams_a, grams_b = _ngrams(a), _ngrams(b)
    if not grams_a or not grams_b:
        return 0.0
    return len(grams_a & grams_b) / len(grams_a | grams_b)


def dedupe_questions(questions: list[PlannedQuestion]) -> list[PlannedQuestion]:
    """Keep the first of any pair with the same material+subtype or similar text.

    Text similarity is only compared when the two questions have no source quote or the same
    one; questions about different materials are never merged.
    """
    kept: list[PlannedQuestion] = []
    for question in questions:
        duplicate = False
        for other in kept:
            mine, theirs = question.source_quote, other.source_quote
            if mine is not None and theirs is not None:
                if normalize_whitespace(mine) != normalize_whitespace(theirs):
                    # Different materials may share a template ("A 프로젝트에서 ... 역할은?").
                    continue
                if question.subtype == other.subtype:
                    duplicate = True
                    break
            if text_similarity(question.text, other.text) >= SIMILARITY_THRESHOLD:
                duplicate = True
                break
        if not duplicate:
            kept.append(question)
    return kept
