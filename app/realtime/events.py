from typing import Any, Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, Field

EventName = Literal[
    "session.ready",
    "session.started",
    "feedback",
    "script.progress",
    "transcript.partial",
    "transcript.final",
    "metrics.snapshot",
    "session.completed",
    "error",
    "ping",
    "pong",
]


class RealtimeEvent(BaseModel):
    event: EventName
    version: int = 1
    session_id: UUID
    sequence: int = Field(ge=0)
    timestamp_ms: int = Field(ge=0)
    module: Literal["gaze", "speech_rate", "pronunciation", "script_sync", "system"] = "system"
    level: Literal["info", "good", "warning", "critical"] = "info"
    data: dict[str, Any] = Field(default_factory=dict)
    trace_id: UUID = Field(default_factory=uuid4)


class ClientEvent(BaseModel):
    event: Literal["ping", "session.start", "transcript.partial", "transcript.final"]
    timestamp_ms: int = Field(default=0, ge=0)
    data: dict[str, Any] = Field(default_factory=dict)
