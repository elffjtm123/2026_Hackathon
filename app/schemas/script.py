from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field, field_validator


class ScriptAnalyzeRequest(BaseModel):
    script: str
    time_limit_seconds: int


class ScriptAnalyzeResponse(BaseModel):
    normalized_script: str
    syllable_count: int
    target_syllables_per_minute: float
    estimated_duration_seconds: int
    timeline: list[dict[str, Any]]
    warnings: list[str]


class StylePresetResponse(BaseModel):
    id: str
    name: str
    description: str
    traits: list[str]


class StyleTransferRequest(BaseModel):
    script: str
    time_limit_seconds: int
    language: str = "ko"
    style_vector: dict[str, float]
    intensity: float = Field(default=0.5, ge=0, le=1)
    preserve_facts: bool = True
    preserve_length: bool = True
    session_id: UUID | None = None

    @field_validator("style_vector")
    @classmethod
    def non_empty_non_negative_vector(cls, value: dict[str, float]) -> dict[str, float]:
        if not value or any(weight < 0 for weight in value.values()) or sum(value.values()) <= 0:
            raise ValueError("style_vector must contain non-negative weights with a positive sum")
        return value


class StyleTransferResponse(BaseModel):
    job_id: UUID
    status: str
    original_script: str
    transformed_script: str | None
    estimated_duration_seconds: int | None
    change_summary: list[str]
    warnings: list[str]
    safety: dict[str, Any]
    style_vector: dict[str, float]
    provider: str
    created_at: datetime
