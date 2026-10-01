from typing import Any, Literal
from uuid import UUID, uuid4

from pydantic import AliasChoices, BaseModel, Field, model_validator

from app.schemas.session import AnalysisSettings

EventName = Literal[
    "session.ready",
    "session.started",
    "session.calibrating",
    "session.running",
    "session.draining",
    "media.ack",
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


class ModuleStatus(BaseModel):
    provider: str
    model: str | None = None
    device: str | None = None
    status: Literal["ready", "unavailable"]
    reason: str | None = None


class SessionStartData(BaseModel):
    mode: Literal["presentation", "interview"] = "presentation"
    settings: AnalysisSettings = Field(default_factory=AnalysisSettings)
    script: str | None = Field(default=None, max_length=20_000)
    time_limit_seconds: int | None = Field(
        default=None,
        ge=30,
        le=3600,
        validation_alias=AliasChoices("time_limit_seconds", "timeLimitSeconds"),
    )

    @model_validator(mode="after")
    def validate_script_pair(self) -> "SessionStartData":
        if (self.script is None) != (self.time_limit_seconds is None):
            raise ValueError("script and time limit must be provided together")
        if self.mode == "interview" and self.script is not None:
            raise ValueError("interview does not accept a presentation script")
        return self


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
    event: Literal[
        "ping",
        "session.start",
        "session.end",
        "calibration.start",
    ]
    timestamp_ms: int = Field(default=0, ge=0)
    data: dict[str, Any] = Field(default_factory=dict)


class V2ClientEvent(ClientEvent):
    version: Literal[2]
    session_id: UUID | None
    sequence: int = Field(ge=1)
    module: Literal["system"]
    level: Literal["info"]
