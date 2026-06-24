from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.db.models.session import PracticeType, SessionStatus


class AnalysisSettings(BaseModel):
    gaze_enabled: bool = True
    speech_rate_enabled: bool = True
    filler_words_enabled: bool = True
    pronunciation_enabled: bool = True
    karaoke_guide_enabled: bool = True
    style_transfer_enabled: bool = True


class SessionCreate(BaseModel):
    type: PracticeType
    title: str = Field(min_length=1, max_length=160)
    script: str | None = None
    time_limit_seconds: int | None = None
    settings: AnalysisSettings = Field(default_factory=AnalysisSettings)


class SessionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    user_id: UUID
    type: PracticeType
    title: str
    status: SessionStatus
    started_at: datetime | None
    ended_at: datetime | None
    duration_ms: int | None
    original_script: str | None
    active_script: str | None
    time_limit_seconds: int | None
    script_syllable_count: int | None
    target_syllables_per_minute: float | None
    settings: dict[str, Any]
    created_at: datetime
    updated_at: datetime


class SessionListResponse(BaseModel):
    items: list[SessionResponse]
    total: int
    page: int
    page_size: int


class WebRTCOffer(BaseModel):
    sdp: str = Field(min_length=1, max_length=1_000_000)
    type: Literal["offer"]


class WebRTCAnswer(BaseModel):
    sdp: str
    type: Literal["answer"] = "answer"


class ReportResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    session_id: UUID
    overall_score: float
    gaze_score: float
    speech_rate_score: float
    filler_word_score: float
    pronunciation_clarity_score: float | None
    script_completion_ratio: float | None
    time_adherence_score: float | None
    gaze_away_count: int
    gaze_away_duration_ms: int
    average_syllables_per_minute: float
    filler_word_counts: dict[str, int]
    transcript: str | None
    timeline: list[dict[str, Any]]
    summary: dict[str, Any]
    gaze_metrics: dict[str, Any]
    speech_rate_metrics: dict[str, Any]
    pronunciation_metrics: dict[str, Any]
    script_sync_metrics: dict[str, Any]
    scoring_version: str
    created_at: datetime
