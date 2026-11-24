from typing import Literal

from pydantic import BaseModel, Field, field_validator

from app.modules.interview.question_bank import MAX_JOB_NAME_CHARS


class DocumentWarningOut(BaseModel):
    code: Literal["no_text", "truncated"]
    message: str


class InterviewDocumentOut(BaseModel):
    kind: Literal["cover_letter", "resume", "portfolio"]
    text: str
    warnings: list[DocumentWarningOut]


MAX_EXCLUDE_IDS = 50


class InterviewPlanDocumentIn(BaseModel):
    kind: Literal["cover_letter", "resume", "portfolio"]
    text: str


class InterviewPlanRequest(BaseModel):
    documents: list[InterviewPlanDocumentIn] = Field(max_length=3)
    job: str | None = Field(default=None, max_length=MAX_JOB_NAME_CHARS)
    # Ordered oldest to newest, as `sample_common` expects.
    exclude_common_ids: list[str] = Field(default_factory=list, max_length=MAX_EXCLUDE_IDS)

    @field_validator("job")
    @classmethod
    def _blank_job_is_none(cls, value: str | None) -> str | None:
        return (value or "").strip() or None

    @field_validator("documents")
    @classmethod
    def _unique_kinds(cls, value: list[InterviewPlanDocumentIn]) -> list[InterviewPlanDocumentIn]:
        if len({d.kind for d in value}) != len(value):
            raise ValueError("document kinds must be unique")
        return value

    @field_validator("exclude_common_ids")
    @classmethod
    def _id_length(cls, value: list[str]) -> list[str]:
        if any(len(i) > 64 for i in value):
            raise ValueError("exclude id too long")
        return value


class PlannedQuestionOut(BaseModel):
    id: str
    kind: Literal["common", "document", "follow_up"]
    subtype: str
    text: str
    intent: str
    source_quote: str | None
    rubric_items: list[str]
    parent_id: str | None
    bank_id: str | None
    round: Literal[1, 2]


class InterviewPlanOut(BaseModel):
    interview_id: str
    questions: list[PlannedQuestionOut]
    warnings: list[str]
