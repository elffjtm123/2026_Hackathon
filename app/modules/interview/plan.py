"""The result of question generation: ordered questions plus warnings, never document text."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from app.modules.interview.questions import PlannedQuestion

PlanWarning = Literal["few_materials", "document_questions_failed"]


@dataclass
class InterviewPlan:
    questions: list[PlannedQuestion]
    # few_materials: documents gave too few valid materials, common questions filled in.
    # document_questions_failed: the model failed after retry; common questions only.
    warnings: list[PlanWarning] = field(default_factory=list)
