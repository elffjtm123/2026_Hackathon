"""Single-user ownership: a process must be reaped before the next model may load."""

import asyncio
import contextlib
import contextvars
from collections.abc import AsyncIterator
from typing import Any, Literal
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


# Marks code running inside a borrowing block (child tasks inherit it); holds that
# borrow's exit event so a stale value from an earlier borrow never matches.
_IN_BORROW: contextvars.ContextVar[asyncio.Event | None] = contextvars.ContextVar(
    "model_execution_in_borrow", default=None
)

OfflineKind = Literal["summary", "interview_plan", "interview_evaluation"]


class ModelExecution:
    """Owner is None, an offline kind, or a session UUID.

    A session owner is in one phase: running (realtime models loaded or loading),
    suspending/suspended (realtime runtime stopped, ownership kept) or resuming.
    The generation model may only be borrowed while the phase is suspended.
    """

    def __init__(self, runtime: Any) -> None:
        self.runtime = runtime
        self.owner: UUID | str | None = None
        self._starting: asyncio.Task[None] | None = None  # start or resume
        self._stopping: asyncio.Task[None] | None = None
        self._suspending: asyncio.Task[None] | None = None
        self._phase: Literal["running", "suspending", "suspended", "resuming"] = "running"
        self._borrower: asyncio.Task[Any] | None = None
        self._borrow_exited: asyncio.Event | None = None

    @property
    def busy(self) -> bool:
        """True while an offline job or a practice session (even suspended) owns the models."""
        return self.owner is not None

    @property
    def generation_active(self) -> bool:
        """True while an offline job owns the models or a session borrows the generation model."""
        return isinstance(self.owner, str) or self._borrower is not None

    @property
    def realtime_stopped(self) -> bool:
        """True while a session owns the models but its realtime runtime is not running
        (suspending, suspended, resuming), i.e. while the generation model may load."""
        return isinstance(self.owner, UUID) and self._phase != "running"

    def reserve_offline(self, kind: OfflineKind) -> None:
        if self.owner is not None:
            if isinstance(self.owner, UUID):
                raise ValueError("PRACTICE_ACTIVE")
            raise ValueError("SUMMARY_BUSY" if self.owner == "summary" else "INTERVIEW_BUSY")
        self.owner = kind

    def release_offline(self, kind: OfflineKind) -> None:
        if self.owner == kind:
            self.owner = None

    def reserve_summary(self) -> None:
        self.reserve_offline("summary")

    def release_summary(self) -> None:
        self.release_offline("summary")

    async def start_session(self, session_id: UUID) -> None:
        if self.owner == "summary":
            raise ValueError("SUMMARY_BUSY")
        if isinstance(self.owner, str):
            raise ValueError("INTERVIEW_BUSY")
        if self.owner == session_id:
            if self._phase != "running":
                raise ValueError("SESSION_SUSPENDED")
            if self._starting is not None or self._stopping is not None:
                raise ValueError("MODEL_UNAVAILABLE_OR_BUSY")
            return
        if self.owner is not None:
            raise ValueError("SESSION_BUSY")
        self.owner = session_id
        await self._start_runtime()

    async def _start_runtime(self) -> None:
        assert isinstance(self.owner, UUID)
        session_id = self.owner
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

    async def suspend_session(self, session_id: UUID) -> None:
        """Stop the realtime runtime but keep ownership."""
        if self.owner != session_id:
            raise ValueError("SESSION_NOT_OWNER")
        if self._stopping is not None:
            raise ValueError("MODEL_UNAVAILABLE_OR_BUSY")
        if self._phase == "suspending":
            assert self._suspending is not None
            await finish(self._suspending)
            return
        if self._phase == "suspended":
            return
        if self._starting is not None:  # starting or resuming
            raise ValueError("MODEL_UNAVAILABLE_OR_BUSY")
        self._phase = "suspending"

        async def suspend() -> None:
            try:
                await self.runtime.stop()
            except BaseException:
                if self._phase == "suspending":
                    self._phase = "running"
                raise
            if self._phase == "suspending":
                self._phase = "suspended"

        suspending = asyncio.create_task(suspend())
        self._suspending = suspending
        try:
            await finish(suspending)
        finally:
            if suspending.done() and self._suspending is suspending:
                self._suspending = None

    async def resume_session(self, session_id: UUID) -> None:
        """Restart the realtime runtime of a suspended session."""
        if self.owner != session_id:
            raise ValueError("SESSION_NOT_OWNER")
        if self._borrower is not None:
            raise ValueError("BORROW_ACTIVE")
        if self._stopping is not None:
            raise ValueError("MODEL_UNAVAILABLE_OR_BUSY")
        if self._phase == "running":
            return
        if self._phase != "suspended":  # suspending or resuming
            raise ValueError("MODEL_UNAVAILABLE_OR_BUSY")
        self._phase = "resuming"
        await self._start_runtime()
        self._phase = "running"

    @contextlib.asynccontextmanager
    async def borrowing(self, session_id: UUID) -> AsyncIterator[None]:
        """Allow the generation model to load while this session is suspended."""
        if self.owner != session_id:
            raise ValueError("SESSION_NOT_OWNER")
        if self._stopping is not None:
            raise ValueError("SESSION_NOT_SUSPENDED")
        if self._borrower is not None:
            raise ValueError("BORROW_ACTIVE")
        if self._phase != "suspended":
            raise ValueError("SESSION_NOT_SUSPENDED")
        exited = asyncio.Event()
        self._borrower = asyncio.current_task()
        self._borrow_exited = exited
        token = _IN_BORROW.set(exited)
        try:
            yield
        finally:
            self._borrower = None
            self._borrow_exited = None
            exited.set()
            # reset() raises if __aexit__ runs in another context than __aenter__
            with contextlib.suppress(ValueError):
                _IN_BORROW.reset(token)

    async def stop_session(self, session_id: UUID) -> None:
        """Safe in every state.

        Cancels the borrowing task (unless the caller runs inside the borrow block) and
        waits until it has left the block. The runtime is not stopped again when a
        suspend already stopped it. Any task created inside the borrow block (child or
        sibling, awaited or not) counts as inside it, as does the borrowing task: such a
        caller does not cancel the borrower, returns right away, and ownership is
        released when the borrower leaves the block.
        """
        if self.owner != session_id:
            return
        borrower = self._borrower
        from_borrower = borrower is not None and _IN_BORROW.get() is self._borrow_exited
        if borrower is not None and not from_borrower:
            borrower.cancel()
        if self._stopping is None:

            async def reap() -> None:
                try:
                    if self._starting is not None:
                        self._starting.cancel()
                        await asyncio.gather(self._starting, return_exceptions=True)
                    if self._suspending is not None:
                        await asyncio.gather(self._suspending, return_exceptions=True)
                    if self._borrow_exited is not None:
                        await self._borrow_exited.wait()
                    if self._phase != "suspended":
                        await self.runtime.stop()
                    self.owner = None
                    self._phase = "running"
                finally:
                    if self._stopping is asyncio.current_task():
                        self._stopping = None

            self._stopping = asyncio.create_task(reap())
        stopping = self._stopping
        if from_borrower:
            return
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
