"""Lightweight parent-side proxies and cancellation-safe child ownership."""

import asyncio
import contextlib
import os
import sys
import tempfile
from typing import Any, TypeVar

from app.ai.base import AIResult, MediaPayload
from app.ai.worker_transport import (
    MAX_JSON_BYTES,
    MODALITIES,
    MODEL_SETTINGS,
    ProtocolError,
    decode_result,
    encode_frame,
    media_metadata,
    read_frame,
    request_id,
    write_frame,
)
from app.core.config import Settings
from app.realtime.events import ModuleStatus

T = TypeVar("T")


async def _settle(task: asyncio.Task[T]) -> T:
    """Cleanup cannot be interrupted by repeated cancellation of its caller."""
    while True:
        try:
            return await asyncio.shield(task)
        except asyncio.CancelledError:
            if task.done():
                return task.result()


def _consume(task: asyncio.Future[Any]) -> None:
    if not task.cancelled():
        task.exception()


class _Gate:
    def __init__(self) -> None:
        self.future: asyncio.Future[AIResult] | None = None

    @property
    def busy(self) -> bool:
        return self.future is not None and not self.future.done()


class _Proxy:
    def __init__(self, owner: "RealtimeModelProcess", modality: str) -> None:
        self.owner, self.modality = owner, modality
        self.gate = _Gate()

    @property
    def reason(self) -> str:
        status = self.owner.modules[self.modality]
        if status.status != "unavailable":
            raise AttributeError("reason")
        return status.reason or "WORKER_UNAVAILABLE"

    async def infer(self, media: MediaPayload) -> AIResult:
        owner = self.owner
        if owner.modules[self.modality].status != "ready" or owner._stopping:
            raise RuntimeError(getattr(self, "reason", "MODEL_NOT_READY"))
        if self.gate.busy:
            raise RuntimeError("MODEL_BUSY")
        identity = owner._next_id
        message = {
            "type": "infer",
            "id": identity,
            "module": self.modality,
            "media": media_metadata(media),
        }
        request_id(identity)
        encode_frame(message, media.payload)
        owner._next_id += 1
        future: asyncio.Future[AIResult] = asyncio.get_running_loop().create_future()
        future.add_done_callback(_consume)
        self.gate.future = future
        owner._pending[identity] = (self.modality, future)

        async def exchange() -> AIResult:
            try:
                async with owner._write_lock:
                    if owner._writer is None:
                        raise ConnectionError()
                    await write_frame(owner._writer, message, media.payload)
            except (ConnectionError, OSError):
                owner._break("WORKER_DISCONNECTED")
            return await future

        task = asyncio.create_task(exchange())
        owner._exchanges.add(task)
        task.add_done_callback(owner._exchanges.discard)
        task.add_done_callback(_consume)
        return await asyncio.shield(task)


class RealtimeModelProcess:
    def __init__(self, settings: Settings, *, command: list[str] | None = None) -> None:
        self.settings = settings
        self.command = (
            command
            if command is not None
            else [
                sys.executable,
                "-m",
                "app.ai.realtime_worker",
            ]
        )
        self.modules = {
            "gaze": ModuleStatus(
                provider=settings.vision_provider,
                model="MediaPipe Face Landmarker + MobileGaze",
                status="idle",
            ),
            "speech": ModuleStatus(
                provider=settings.stt_provider, model=settings.stt_model, status="idle"
            ),
        }
        self.gaze, self.speech = _Proxy(self, "gaze"), _Proxy(self, "speech")
        self.process: asyncio.subprocess.Process | None = None
        self._directory: tempfile.TemporaryDirectory[str] | None = None
        self._server: asyncio.AbstractServer | None = None
        self._writer: asyncio.StreamWriter | None = None
        self._reader_task: asyncio.Task[None] | None = None
        self._watch_task: asyncio.Task[None] | None = None
        self._spawn_task: asyncio.Task[asyncio.subprocess.Process] | None = None
        self._start_task: asyncio.Task[None] | None = None
        self._stop_task: asyncio.Task[None] | None = None
        self._write_lock = asyncio.Lock()
        self._pending: dict[int, tuple[str, asyncio.Future[AIResult]]] = {}
        self._exchanges: set[asyncio.Task[AIResult]] = set()
        self._next_id = 1
        self._broken = False
        self._stopping = False

    def _status(self, status: str, reason: str | None = None) -> None:
        for key, module in self.modules.items():
            update: dict[str, Any] = {"status": status, "reason": reason}
            if status in {"idle", "loading"}:
                update["device"] = None
            self.modules[key] = module.model_copy(update=update)

    async def start(self) -> None:
        if self._stop_task is not None and not self._stop_task.done():
            await asyncio.shield(self._stop_task)
        if self._start_task is not None and not self._start_task.done():
            task = self._start_task
        else:
            if self.process is not None:
                if not self._broken and self.process.returncode is None:
                    return
                await self.stop()
            self._stopping = False
            self._broken = False
            self._status("loading")
            task = self._start_task = asyncio.create_task(self._start())
        try:
            await asyncio.shield(task)
        except asyncio.CancelledError:
            cleanup = asyncio.create_task(self.stop())
            await _settle(cleanup)
            raise

    async def _start(self) -> None:
        try:
            await asyncio.wait_for(
                self._launch(),
                getattr(self.settings, "realtime_start_timeout_seconds", 120),
            )
        except BaseException as exc:
            self._stopping = True
            if not isinstance(exc, asyncio.CancelledError):
                self._broken = True
                if not any(m.status == "unavailable" for m in self.modules.values()):
                    self._status("unavailable", "WORKER_START_FAILED")
                else:
                    for key, module in self.modules.items():
                        if module.status != "unavailable":
                            self.modules[key] = module.model_copy(
                                update={
                                    "status": "unavailable",
                                    "reason": "WORKER_START_FAILED",
                                }
                            )
            await self._cleanup()
            if isinstance(exc, asyncio.CancelledError):
                if not self._broken:
                    self._status("idle")
                raise
            raise ValueError("MODEL_UNAVAILABLE_OR_BUSY") from None

    async def _launch(self) -> None:
        connection: asyncio.Future[tuple[asyncio.StreamReader, asyncio.StreamWriter]] = (
            asyncio.get_running_loop().create_future()
        )

        def accept(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
            if connection.done() or self._stopping:
                writer.close()
            else:
                connection.set_result((reader, writer))
                self._writer = writer

        # /tmp keeps the Unix socket path below macOS's 104-byte sockaddr limit.
        self._directory = tempfile.TemporaryDirectory(prefix="rt-ai-", dir="/tmp")
        path = self._directory.name + "/ipc.sock"
        self._server = await asyncio.start_unix_server(accept, path=path, limit=MAX_JSON_BYTES)
        os.chmod(path, 0o600)
        self._spawn_task = asyncio.create_task(
            asyncio.create_subprocess_exec(
                *self.command,
                path,
                stdin=asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
        )
        self.process = await asyncio.shield(self._spawn_task)
        self._watch_task = asyncio.create_task(self._watch(connection))
        reader, writer = await connection
        self._server.close()
        await self._server.wait_closed()
        await write_frame(
            writer,
            {
                "type": "init",
                "settings": self.settings.model_dump(
                    mode="json",
                    include=MODEL_SETTINGS,
                ),
            },
        )
        message, payload = await read_frame(reader)
        if message.keys() != {"type", "modules"} or message["type"] != "ready" or payload:
            raise ProtocolError()
        statuses = message["modules"]
        if not isinstance(statuses, dict) or statuses.keys() != MODALITIES:
            raise ProtocolError()
        for name, status in statuses.items():
            if not isinstance(status, dict) or status.keys() != {"status", "reason", "device"}:
                raise ProtocolError()
            if (status["status"], status["reason"]) not in {
                ("ready", None),
                ("unavailable", "MODEL_LOAD_FAILED"),
            } or status["device"] not in {None, "cpu", "mps", "cuda"}:
                raise ProtocolError()
            self.modules[name] = self.modules[name].model_copy(update=status)
        if any(m.status != "ready" for m in self.modules.values()):
            raise ValueError("MODEL_UNAVAILABLE_OR_BUSY")
        self._reader_task = asyncio.create_task(self._read(reader))

    async def _watch(
        self,
        connection: asyncio.Future[tuple[asyncio.StreamReader, asyncio.StreamWriter]],
    ) -> None:
        assert self.process is not None
        await self.process.wait()
        if not connection.done():
            connection.set_exception(RuntimeError("WORKER_EXITED"))
        if not self._stopping:
            self._break("WORKER_EXITED")

    async def _read(self, reader: asyncio.StreamReader) -> None:
        try:
            while True:
                message, payload = await read_frame(reader)
                identity = request_id(message.get("id"))
                pending = self._pending.get(identity)
                if pending is None or message.get("module") != pending[0] or payload:
                    raise ProtocolError()
                modality, future = pending
                if message.keys() == {"type", "id", "module", "result"} and (
                    message["type"] == "result"
                ):
                    result = decode_result(message["result"])
                    if result.source != ("gaze" if modality == "gaze" else "speech_rate"):
                        raise ProtocolError()
                    future.set_result(result)
                elif message == {
                    "type": "error",
                    "id": identity,
                    "module": modality,
                    "reason": "INFERENCE_FAILED",
                }:
                    future.set_exception(RuntimeError("INFERENCE_FAILED"))
                else:
                    raise ProtocolError()
                del self._pending[identity]
        except (Exception, asyncio.CancelledError):
            if not self._stopping:
                self._break("WORKER_DISCONNECTED")

    def _break(self, reason: str) -> None:
        self._broken = True
        self._status("unavailable", reason)
        self._fail_pending(reason)
        if self._stop_task is None or self._stop_task.done():
            self._stopping = True
            self._stop_task = asyncio.create_task(self._stop())
            self._stop_task.add_done_callback(_consume)

    def _fail_pending(self, reason: str) -> None:
        for _, future in self._pending.values():
            if not future.done():
                future.set_exception(RuntimeError(reason))
        self._pending.clear()

    async def stop(self) -> None:
        if self._stop_task is None or self._stop_task.done():
            self._stopping = True
            self._stop_task = asyncio.create_task(self._stop())
        task = self._stop_task
        try:
            await asyncio.shield(task)
        except asyncio.CancelledError:
            await _settle(task)
            raise

    async def _stop(self) -> None:
        if self._start_task is not None and not self._start_task.done():
            self._start_task.cancel()
            await asyncio.gather(self._start_task, return_exceptions=True)
        await self._cleanup()
        if not self._broken:
            self._status("idle")

    async def _cleanup(self) -> None:
        if self._server is not None:
            self._server.close()
            await self._server.wait_closed()
            self._server = None
        if self._spawn_task is not None:
            with contextlib.suppress(Exception):
                self.process = await asyncio.shield(self._spawn_task)
            self._spawn_task = None
        if self._writer is not None:
            self._writer.close()
        if self.process is not None:
            process = self.process
            try:
                await asyncio.wait_for(process.wait(), 5)
            except asyncio.TimeoutError:
                with contextlib.suppress(ProcessLookupError):
                    process.terminate()
                try:
                    await asyncio.wait_for(process.wait(), 1)
                except asyncio.TimeoutError:
                    with contextlib.suppress(ProcessLookupError):
                        process.kill()
                    await process.wait()
            self.process = None
        self._fail_pending("WORKER_STOPPED")
        tasks = [task for task in (self._reader_task, self._watch_task) if task is not None]
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        await asyncio.gather(*self._exchanges, return_exceptions=True)
        self._reader_task = self._watch_task = None
        self._writer = None
        if self._directory is not None:
            self._directory.cleanup()
            self._directory = None
