import enum
from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import JSON, DateTime, Enum, Float, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class PracticeType(enum.StrEnum):
    presentation = "presentation"
    interview = "interview"


class SessionStatus(enum.StrEnum):
    created = "created"
    active = "active"
    processing = "processing"
    completed = "completed"
    failed = "failed"


class PracticeSession(Base):
    __tablename__ = "practice_sessions"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    type: Mapped[PracticeType] = mapped_column(Enum(PracticeType, native_enum=False))
    title: Mapped[str] = mapped_column(String(160))
    status: Mapped[SessionStatus] = mapped_column(
        Enum(SessionStatus, native_enum=False), default=SessionStatus.created, index=True
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    duration_ms: Mapped[int | None] = mapped_column(Integer)
    original_script: Mapped[str | None] = mapped_column(Text)
    active_script: Mapped[str | None] = mapped_column(Text)
    time_limit_seconds: Mapped[int | None] = mapped_column(Integer)
    script_syllable_count: Mapped[int | None] = mapped_column(Integer)
    target_syllables_per_minute: Mapped[float | None] = mapped_column(Float)
    settings: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    user = relationship("User", back_populates="sessions")
    report = relationship(
        "SessionReport", back_populates="session", cascade="all, delete-orphan", uselist=False
    )
