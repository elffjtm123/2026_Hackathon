"""Interview composition (question counts and order) and turn-taking thresholds."""

from __future__ import annotations

from dataclasses import dataclass

from app.modules.interview.questions import (
    EXPERIENCE,
    JOB,
    SELF_INTRODUCTION,
    CommonCategory,
    PlannedQuestion,
)

# Stage rank per subtype: 자기소개 → 지원 동기 → job/experience (+ 강점·약점) → personality
# → 입사 후 계획 → 마무리. Unknown subtypes sort with job/experience.
_STAGE = {
    CommonCategory.SELF_INTRODUCTION.value: 0,
    CommonCategory.MOTIVATION.value: 1,
    JOB: 2,
    EXPERIENCE: 2,
    CommonCategory.STRENGTH_WEAKNESS.value: 2,
    CommonCategory.PERSONALITY_BEHAVIORAL.value: 3,
    CommonCategory.PERSONALITY_SITUATIONAL.value: 3,
    CommonCategory.FUTURE_PLAN.value: 4,
    CommonCategory.CLOSING.value: 5,
}
_DEFAULT_STAGE = 2


@dataclass
class Composition:
    common_basic: int = 2  # 자기소개 + 1
    personality_behavioral: int = 1
    personality_situational: int = 1
    job: int = 2
    experience: int = 2
    max_follow_ups: int = 2
    include_closing: bool = True  # 마무리 is extra and never scored

    @property
    def personality(self) -> int:
        return self.personality_behavioral + self.personality_situational

    def order_questions(self, questions: list[PlannedQuestion]) -> list[PlannedQuestion]:
        """Stable sort into interview order."""
        return sorted(questions, key=lambda q: _STAGE.get(q.subtype, _DEFAULT_STAGE))


@dataclass
class TurnRules:
    """Thresholds in milliseconds (plan section 7); tune by demo experiments."""

    reading_base_ms: int = 3000
    reading_chars_per_second: int = 7
    reading_max_ms: int = 15000
    silence_ms: int = 4000
    min_answer_ms: int = 10000
    answer_limit_ms: int = 120000
    self_intro_limit_ms: int = 90000
    no_response_ms: int = 15000
    endpoint_ms: int = 500
    final_wait_cap_ms: int = 3000
    # Segmenter limits: longest single utterance, and speech start precedes the first voiced
    # frame by this pre-roll.
    max_utterance_ms: int = 8000
    pre_roll_ms: int = 200

    def reading_ms(self, text: str) -> int:
        ms = self.reading_base_ms + round(len(text) / self.reading_chars_per_second * 1000)
        return min(self.reading_max_ms, ms)

    def answer_limit_for(self, question: PlannedQuestion) -> int:
        if question.subtype == SELF_INTRODUCTION:
            return self.self_intro_limit_ms
        return self.answer_limit_ms
