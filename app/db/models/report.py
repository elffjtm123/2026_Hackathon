from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    false,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class SessionReport(Base):
    __tablename__ = "session_reports"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    session_id: Mapped[UUID] = mapped_column(
        ForeignKey("practice_sessions.id", ondelete="CASCADE"), unique=True, index=True
    )
    overall_score: Mapped[float | None] = mapped_column(Float)
    gaze_score: Mapped[float | None] = mapped_column(Float)
    speech_rate_score: Mapped[float | None] = mapped_column(Float)
    filler_word_score: Mapped[float | None] = mapped_column(Float)
    incomplete: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())
    pronunciation_clarity_score: Mapped[float | None] = mapped_column(Float)
    script_completion_ratio: Mapped[float | None] = mapped_column(Float)
    time_adherence_score: Mapped[float | None] = mapped_column(Float)
    gaze_away_count: Mapped[int] = mapped_column(Integer, default=0)
    gaze_away_duration_ms: Mapped[int] = mapped_column(Integer, default=0)
    average_syllables_per_minute: Mapped[float | None] = mapped_column(Float)
    filler_word_counts: Mapped[dict[str, int] | None] = mapped_column(JSON(none_as_null=True))
    transcript: Mapped[str | None] = mapped_column(Text)
    timeline: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    summary: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    gaze_metrics: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    speech_rate_metrics: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    pronunciation_metrics: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    script_sync_metrics: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    delivery_metrics: Mapped[dict[str, Any]] = mapped_column(
        JSON, default=dict, server_default=text("'{}'")
    )
    scoring_version: Mapped[str] = mapped_column(String(20), default="v1")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    session = relationship("PracticeSession", back_populates="report")
