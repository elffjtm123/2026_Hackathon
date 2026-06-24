from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field

EventName = Literal[
    "session.ready",
    "session.started",
    "feedback",
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
    session_id: UUID
    sequence: int = Field(ge=0)
    timestamp_ms: int = Field(ge=0)
    data: dict[str, Any] = Field(default_factory=dict)


class ClientEvent(BaseModel):
    event: Literal["ping", "session.start", "transcript.partial", "transcript.final"]
    timestamp_ms: int = Field(default=0, ge=0)
    data: dict[str, Any] = Field(default_factory=dict)
