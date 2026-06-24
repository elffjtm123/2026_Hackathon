from dataclasses import dataclass
from typing import Any, Protocol
from uuid import UUID


@dataclass(slots=True, frozen=True)
class MediaPayload:
    session_id: UUID
    timestamp_ms: int
    payload: bytes


@dataclass(slots=True, frozen=True)
class AIResult:
    source: str
    timestamp_ms: int
    level: str
    message: str
    metrics: dict[str, Any]
    transcript: str | None = None
    is_final: bool | None = None
    latency_ms: int | None = None


class GazeAdapter(Protocol):
    async def infer(self, media: MediaPayload) -> AIResult: ...


class SpeechAdapter(Protocol):
    async def infer(self, media: MediaPayload) -> AIResult: ...
