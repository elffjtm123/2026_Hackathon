from typing import Any

from pydantic import BaseModel, Field


class ScriptSummaryRequest(BaseModel):
    script: str = Field(min_length=1, max_length=20_000)


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
