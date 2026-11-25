"""Evaluation result types (pure data; scoring lives in `rubric`)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from app.modules.interview.questions import RubricItem
from app.modules.interview.rubric import NotEvaluableReason

# not_scored: the question has no rubric items (closing). failed: the model call failed after its
# retry, every applicable item was invalidated, or the time budget ran out.
EvaluationStatus = Literal["evaluated", "not_evaluable", "not_scored", "failed"]
EvidenceSource = Literal["main", "follow_up"]
EvaluationWarning = Literal["item_evaluation_failed", "summary_failed", "evaluation_timeout"]


@dataclass
class Grade:
    grade: int  # 0-4
    evidence_quote: str
    evidence_source: EvidenceSource
    reason: str
    improvement: str


@dataclass
class ItemEvaluation:
    question_id: str
    status: EvaluationStatus
    not_evaluable_reason: NotEvaluableReason | None = None
    grades: dict[RubricItem, Grade] = field(default_factory=dict)
    # Applicable items whose grade was invalidated (shown as "부분 평가" when `partial`).
    excluded_items: list[RubricItem] = field(default_factory=list)
    partial: bool = False
    score: float | None = None  # 0-20
    follow_up_ids: list[str] = field(default_factory=list)  # follow-up questions bundled in


@dataclass
class EvaluationSummary:
    strengths: list[str] = field(default_factory=list)
    improvements: list[str] = field(default_factory=list)
    next_goals: list[str] = field(default_factory=list)


@dataclass
class InterviewEvaluation:
    items: list[ItemEvaluation]
    overall_score: float | None
    summary: EvaluationSummary
    model: str
    elapsed_seconds: float
    warnings: list[EvaluationWarning] = field(default_factory=list)
