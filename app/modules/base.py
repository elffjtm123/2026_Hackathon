from dataclasses import dataclass, field
from typing import Any, Protocol
from uuid import UUID


@dataclass(frozen=True, slots=True)
class SessionContext:
    session_id: UUID
    script: str | None = None
    time_limit_seconds: int | None = None
    settings: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class MediaItem:
    timestamp_ms: int
    payload: Any
    is_final: bool = False


@dataclass(frozen=True, slots=True)
class ModuleFeedback:
    module: str
    level: str
    data: dict[str, Any]
    event: str = "feedback"


class AnalysisModule(Protocol):
    name: str

    async def start(self, context: SessionContext) -> None: ...

    async def process(self, item: MediaItem) -> list[ModuleFeedback]: ...

    async def finish(self) -> dict[str, Any]: ...

    async def close(self) -> None: ...
