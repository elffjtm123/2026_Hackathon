from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.db.models.session import PracticeType, SessionStatus


class AnalysisSettings(BaseModel):
    gaze_enabled: bool = True
    speech_rate_enabled: bool = True
    filler_words_enabled: bool = True


class SessionCreate(BaseModel):
    type: PracticeType
    title: str = Field(min_length=1, max_length=160)
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
    gaze_away_count: int
    gaze_away_duration_ms: int
    average_syllables_per_minute: float
    filler_word_counts: dict[str, int]
    transcript: str | None
    timeline: list[dict[str, Any]]
    summary: dict[str, Any]
    created_at: datetime
