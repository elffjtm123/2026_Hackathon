"""Single-user ownership: a process must be reaped before the next model may load."""

import asyncio
from typing import Any
from uuid import UUID


async def finish(task: asyncio.Task[Any]) -> Any:
    cancelled = False
    while not task.done():
        try:
            await asyncio.shield(task)
        except asyncio.CancelledError:
            cancelled = True
    result = task.result()
    if cancelled:
        raise asyncio.CancelledError
    return result


class ModelExecution:
    def __init__(self, runtime: Any) -> None:
        self.runtime = runtime
        self.owner: UUID | str | None = None
        self._starting: asyncio.Task[None] | None = None
        self._stopping: asyncio.Task[None] | None = None

    def reserve_summary(self) -> None:
        if self.owner is not None:
            raise ValueError("SUMMARY_BUSY" if self.owner == "summary" else "PRACTICE_ACTIVE")
        self.owner = "summary"

    def release_summary(self) -> None:
        if self.owner == "summary":
            self.owner = None

    async def start_session(self, session_id: UUID) -> None:
        if self.owner == "summary":
            raise ValueError("SUMMARY_BUSY")
        if self.owner == session_id:
            if self._starting is not None or self._stopping is not None:
                raise ValueError("MODEL_UNAVAILABLE_OR_BUSY")
            return
        if self.owner is not None:
            raise ValueError("SESSION_BUSY")
        self.owner = session_id
        starting = asyncio.create_task(self.runtime.start())
        self._starting = starting
        try:
            await asyncio.shield(starting)
        except BaseException:
            await self.stop_session(session_id)
            raise
        finally:
            if self._starting is starting:
                self._starting = None

    async def stop_session(self, session_id: UUID) -> None:
        if self.owner != session_id:
            return
        if self._stopping is None:

            async def reap() -> None:
                if self._starting is not None:
                    self._starting.cancel()
                    await asyncio.gather(self._starting, return_exceptions=True)
                await self.runtime.stop()
                self.owner = None

            self._stopping = asyncio.create_task(reap())
        stopping = self._stopping
        try:
            await finish(stopping)
        finally:
            if stopping.done() and self._stopping is stopping:
                self._stopping = None

    async def close(self) -> None:
        if isinstance(self.owner, UUID):
            await self.stop_session(self.owner)
        else:
            await finish(asyncio.create_task(self.runtime.stop()))
