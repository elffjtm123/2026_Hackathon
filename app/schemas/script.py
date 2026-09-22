from typing import Any

from pydantic import BaseModel


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
