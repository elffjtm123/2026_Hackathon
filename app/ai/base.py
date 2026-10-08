import asyncio
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass
from typing import Any, Protocol, TypeVar
from uuid import UUID


@dataclass(slots=True, frozen=True)
class MediaPayload:
    session_id: UUID
    timestamp_ms: int
    payload: bytes
    sequence: int = 0
    start_sample: int = 0
    sample_count: int = 0
    format: str = "legacy"
    utterance_id: str | None = None
    end_ms: int | None = None
    voiced_ms: int | None = None


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


class UnavailableSpeechAdapter:
    def __init__(self, reason: str) -> None:
        self.reason = reason

    async def infer(self, media: MediaPayload) -> AIResult:
        raise RuntimeError(self.reason)


T = TypeVar("T")


class InferenceGate:
    """Cancellation of the waiter never releases a still-running native model."""

    def __init__(self) -> None:
        self.executor = ThreadPoolExecutor(max_workers=1)
        self.future: Future[Any] | None = None

    @property
    def busy(self) -> bool:
        return self.future is not None and not self.future.done()

    async def run_once(self, call: Callable[[], T]) -> T:
        if self.busy:
            raise RuntimeError("model busy: previous inference is still running")
        self.future = self.executor.submit(call)
        return await asyncio.shield(asyncio.wrap_future(self.future))

    def close(self) -> None:
        self.executor.shutdown(wait=False)
