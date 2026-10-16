import asyncio
import importlib.util
import os
import signal
import struct
import sys
import tempfile
from dataclasses import replace
from typing import Any
from uuid import UUID

import pytest

from app.ai.base import MediaPayload
from app.core.config import Settings


def runtime(*flags: str) -> Any:
    from app.ai.realtime_process import RealtimeModelProcess

    return RealtimeModelProcess(
        Settings(_env_file=None),
        command=[sys.executable, "-m", "tests.model_worker_fixture", *flags],
    )


def media(payload: bytes = b"\x00\xff\x03\x80") -> MediaPayload:
    return MediaPayload(
        UUID("00000000-0000-0000-0000-000000000123"),
        1234,
        payload,
        sequence=42,
        start_sample=16000,
        sample_count=2,
        format="pcm16",
        utterance_id="발화-7",
        end_ms=1444,
        voiced_ms=123,
    )


async def busy(proxy: Any) -> None:
    for _ in range(200):
        if proxy.gate.busy:
            return
        await asyncio.sleep(0.005)
    pytest.fail("request was not accepted")


def gone(pid: int) -> None:
    with pytest.raises(ProcessLookupError):
        os.kill(pid, 0)


def test_sidecar_exists_without_loading_models() -> None:
    assert importlib.util.find_spec("app.ai.realtime_process") is not None
    worker = runtime()
    assert worker.process is None
    assert {value.status for value in worker.modules.values()} == {"idle"}
    assert not hasattr(worker.gaze, "reason")
    assert not hasattr(worker.speech, "reason")


async def test_native_round_trip_preserves_every_field_and_reaps() -> None:
    worker = runtime()
    modules = worker.modules
    try:
        await worker.start()
        assert worker.modules is modules
        assert {value.status for value in modules.values()} == {"ready"}
        assert not hasattr(worker.speech, "reason")
        process = worker.process
        assert isinstance(process, asyncio.subprocess.Process)
        pid = process.pid
        assert pid != os.getpid()
        result = await worker.speech.infer(media())
        assert result.source == "speech_rate"
        assert result.timestamp_ms == 1234
        assert result.level == "warning"
        assert result.message == "검증 결과"
        assert result.transcript == "발화 내용"
        assert result.is_final is True
        assert result.latency_ms == 23
        assert result.metrics == {
            "pid": pid,
            "media": {
                "session_id": "00000000-0000-0000-0000-000000000123",
                "timestamp_ms": 1234,
                "payload": "00ff0380",
                "sequence": 42,
                "start_sample": 16000,
                "sample_count": 2,
                "format": "pcm16",
                "utterance_id": "발화-7",
                "end_ms": 1444,
                "voiced_ms": 123,
            },
            "nested": [None, True, 1.25],
        }
        await worker.start()
        assert worker.process is process
    finally:
        await worker.stop()
    assert process.returncode == 0
    gone(pid)
    assert worker.process is None
    assert {value.status for value in modules.values()} == {"idle"}
    await worker.stop()


async def test_modalities_are_independent_and_cancelled_waiter_keeps_slot() -> None:
    worker = runtime()
    await worker.start()
    try:
        slow = asyncio.create_task(worker.gaze.infer(media(b"slow")))
        await busy(worker.gaze)
        slow.cancel()
        with pytest.raises(asyncio.CancelledError):
            await slow
        assert worker.gaze.gate.busy
        with pytest.raises(RuntimeError, match="BUSY"):
            await worker.gaze.infer(media())
        speech = await asyncio.wait_for(worker.speech.infer(media()), 0.3)
        assert speech.source == "speech_rate"
        assert worker.gaze.gate.busy
        for _ in range(200):
            if not worker.gaze.gate.busy:
                break
            await asyncio.sleep(0.005)
        assert not worker.gaze.gate.busy
        assert (await worker.gaze.infer(media())).source == "gaze"
    finally:
        await worker.stop()


async def test_crash_resolves_all_pending_and_restart_is_safe() -> None:
    worker = runtime()
    await worker.start()
    old_pid = worker.process.pid
    try:
        hang = asyncio.create_task(worker.gaze.infer(media(b"hang")))
        await busy(worker.gaze)
        crash = asyncio.create_task(worker.speech.infer(media(b"crash")))
        results = await asyncio.wait_for(asyncio.gather(hang, crash, return_exceptions=True), 3)
        assert all(isinstance(result, RuntimeError) for result in results)
        assert {value.status for value in worker.modules.values()} == {"unavailable"}
        assert hasattr(worker.gaze, "reason")
        await worker.start()
        gone(old_pid)
        assert worker.process.pid != old_pid
        assert (await worker.speech.infer(media())).transcript == "발화 내용"
    finally:
        await worker.stop()


async def test_inference_errors_are_sanitized_and_slot_recovers() -> None:
    worker = runtime()
    await worker.start()
    try:
        with pytest.raises(RuntimeError, match="^INFERENCE_FAILED$"):
            await worker.speech.infer(media(b"error"))
        assert not worker.speech.gate.busy
        assert (await worker.speech.infer(media())).is_final
    finally:
        await worker.stop()


async def test_failed_factory_reports_only_safe_reason() -> None:
    worker = runtime("--load-fail")
    try:
        with pytest.raises(ValueError, match="^MODEL_UNAVAILABLE_OR_BUSY$"):
            await worker.start()
        assert worker.modules["gaze"].status == "unavailable"
        assert worker.gaze.reason == "MODEL_LOAD_FAILED"
        assert worker.process is None
        with pytest.raises(RuntimeError, match="^MODEL_LOAD_FAILED$"):
            await worker.gaze.infer(media())
    finally:
        await worker.stop()
    assert worker.modules["gaze"].status == "unavailable"


async def test_parent_eof_exits_child_even_during_native_inference() -> None:
    worker = runtime()
    await worker.start()
    process = worker.process
    try:
        task = asyncio.create_task(worker.gaze.infer(media(b"hang")))
        await busy(worker.gaze)
        worker._writer.close()
        await asyncio.wait_for(process.wait(), 2)
        assert process.returncode == 0
        with pytest.raises(RuntimeError):
            await task
    finally:
        await worker.stop()
    gone(process.pid)


async def test_loading_and_repeated_start_cancellation_reap_partial_child() -> None:
    worker = runtime("--slow-load")
    task = asyncio.create_task(worker.start())
    for _ in range(400):
        if worker.process is not None or task.done():
            break
        await asyncio.sleep(0.005)
    assert worker.process is not None
    process = worker.process
    assert {value.status for value in worker.modules.values()} == {"loading"}
    task.cancel()
    await asyncio.sleep(0)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(task, 3)
    assert process.returncode is not None
    gone(process.pid)
    await worker.stop()


async def test_cancellation_during_spawn_still_captures_and_reaps_child(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    worker = runtime()
    spawned = asyncio.Event()
    release = asyncio.Event()
    original = asyncio.create_subprocess_exec
    processes = []

    async def delayed_spawn(*args: Any, **kwargs: Any) -> asyncio.subprocess.Process:
        process = await original(*args, **kwargs)
        processes.append(process)
        spawned.set()
        await release.wait()
        return process

    monkeypatch.setattr(asyncio, "create_subprocess_exec", delayed_spawn)
    task = asyncio.create_task(worker.start())
    await asyncio.wait_for(spawned.wait(), 3)
    task.cancel()
    await asyncio.sleep(0)
    task.cancel()
    release.set()
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(task, 3)
    assert len(processes) == 1
    assert processes[0].returncode is not None
    gone(processes[0].pid)
    await worker.stop()


async def test_concurrent_start_stop_and_cancelled_stop_are_reaped() -> None:
    worker = runtime()
    await asyncio.gather(worker.start(), worker.start())
    process = worker.process
    task = asyncio.create_task(worker.stop())
    await asyncio.sleep(0)
    task.cancel()
    await asyncio.sleep(0)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    gone(process.pid)
    assert worker.process is None
    await worker.start()
    assert worker.process is not None
    assert worker.process.pid != process.pid
    await asyncio.gather(worker.stop(), worker.stop())


@pytest.mark.parametrize("header", [struct.pack(">II", 65537, 0), struct.pack(">II", 2, 2097153)])
async def test_transport_rejects_oversized_lengths_before_reading_body(header: bytes) -> None:
    from app.ai.worker_transport import ProtocolError, read_frame

    reader = asyncio.StreamReader()
    reader.feed_data(header)
    with pytest.raises(ProtocolError):
        await asyncio.wait_for(read_frame(reader), 0.1)


@pytest.mark.parametrize(
    "raw",
    [
        b"[]",
        b"null",
        b'{"x":NaN}',
        b'{"x":1e999}',
        b'{"x":1,"x":2}',
        b"not-json",
    ],
)
async def test_transport_rejects_malformed_metadata(raw: bytes) -> None:
    from app.ai.worker_transport import ProtocolError, read_frame

    reader = asyncio.StreamReader()
    reader.feed_data(struct.pack(">II", len(raw), 0) + raw)
    with pytest.raises(ProtocolError):
        await read_frame(reader)


async def test_oversized_or_invalid_media_does_not_reserve_slot() -> None:
    worker = runtime()
    await worker.start()
    try:
        for invalid in (media(b"x" * 2097153), replace(media(), timestamp_ms=-1)):
            with pytest.raises(ValueError):
                await worker.speech.infer(invalid)
            assert not worker.speech.gate.busy
        assert (await worker.speech.infer(media())).is_final
    finally:
        await worker.stop()


async def test_worker_rejects_unknown_modality_without_echoing_content() -> None:
    from app.ai.worker_transport import MODEL_SETTINGS, read_frame, write_frame

    connection = asyncio.get_running_loop().create_future()

    def accept(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        connection.set_result((reader, writer))

    directory = tempfile.TemporaryDirectory(prefix="rt-test-", dir="/tmp")
    path = directory.name + "/worker.sock"
    server = await asyncio.start_unix_server(accept, path=path)
    process = await asyncio.create_subprocess_exec(
        sys.executable,
        "-m",
        "tests.model_worker_fixture",
        path,
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.DEVNULL,
    )
    try:
        reader, writer = await asyncio.wait_for(connection, 3)
        await write_frame(
            writer,
            {
                "type": "init",
                "settings": Settings(_env_file=None).model_dump(include=MODEL_SETTINGS),
            },
        )
        hello, _ = await asyncio.wait_for(read_frame(reader), 3)
        assert hello["type"] == "ready"
        await write_frame(writer, {"type": "infer", "id": 1, "module": "PRIVATE_BAD"})
        assert await asyncio.wait_for(reader.read(), 2) == b""
        await asyncio.wait_for(process.wait(), 2)
        writer.close()
    finally:
        server.close()
        await server.wait_closed()
        if process.returncode is None:
            process.kill()
        await process.wait()
        directory.cleanup()


async def test_socket_is_private_and_only_model_settings_cross_ipc(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.ai import realtime_process

    worker = runtime()
    original = realtime_process.write_frame
    init_messages = []

    async def capture(writer: Any, metadata: Any, payload: bytes = b"") -> None:
        if metadata.get("type") == "init":
            init_messages.append(metadata)
        await original(writer, metadata, payload)

    monkeypatch.setattr(realtime_process, "write_frame", capture)
    await worker.start()
    directory = worker._directory.name
    try:
        assert os.stat(directory).st_mode & 0o777 == 0o700
        assert os.stat(directory + "/ipc.sock").st_mode & 0o777 == 0o600
        assert len(init_messages) == 1
        assert set(init_messages[0]["settings"]) == {
            "vision_provider",
            "face_landmarker_path",
            "stt_provider",
            "stt_model",
            "stt_library_path",
            "stt_device",
            "stt_context",
            "stt_silence_rms_threshold",
        }
    finally:
        await worker.stop()
    with pytest.raises(FileNotFoundError):
        os.stat(directory)


async def test_startup_deadline_reaps_and_preserves_unavailable_status() -> None:
    worker = runtime("--slow-load")
    worker.settings = worker.settings.model_copy(update={"realtime_start_timeout_seconds": 0.2})
    with pytest.raises(ValueError, match="^MODEL_UNAVAILABLE_OR_BUSY$"):
        await asyncio.wait_for(worker.start(), 3)
    assert worker.process is None
    assert {m.status for m in worker.modules.values()} == {"unavailable"}
    await worker.stop()
    assert {m.status for m in worker.modules.values()} == {"unavailable"}


async def test_child_exit_before_handshake_is_load_failure_not_cancellation() -> None:
    from app.ai.realtime_process import RealtimeModelProcess

    worker = RealtimeModelProcess(
        Settings(_env_file=None),
        command=[sys.executable, "-c", "raise SystemExit(19)"],
    )
    with pytest.raises(ValueError, match="^MODEL_UNAVAILABLE_OR_BUSY$"):
        await asyncio.wait_for(worker.start(), 3)
    assert worker.process is None
    assert {m.status for m in worker.modules.values()} == {"unavailable"}
    await worker.stop()


async def test_repeated_stop_cancellation_still_kills_and_reaps_stubborn_child() -> None:
    worker = runtime("--ignore-eof")
    await worker.start()
    process = worker.process
    task = asyncio.create_task(worker.stop())
    await asyncio.sleep(0.05)
    task.cancel()
    await asyncio.sleep(0.05)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(task, 8)
    assert process.returncode == -signal.SIGKILL
    gone(process.pid)
    assert worker.process is None
    await worker.stop()


@pytest.mark.parametrize("fault", ["id", "module", "type", "field", "extra", "reason"])
async def test_invalid_reply_fails_pending_without_raw_content(
    monkeypatch: pytest.MonkeyPatch,
    fault: str,
) -> None:
    from app.ai import realtime_process

    original = realtime_process.read_frame

    async def corrupt(reader: Any) -> Any:
        message, payload = await original(reader)
        if message.get("type") == "result":
            if fault == "field":
                message["result"]["is_final"] = "PRIVATE_INVALID"
            elif fault == "extra":
                message["result"]["extra"] = "PRIVATE_INVALID"
            elif fault == "reason":
                message = {
                    "type": "error",
                    "id": message["id"],
                    "module": message["module"],
                    "reason": "PRIVATE_INVALID",
                }
            else:
                message[fault] = 999 if fault == "id" else "PRIVATE_INVALID"
        return message, payload

    monkeypatch.setattr(realtime_process, "read_frame", corrupt)
    worker = runtime()
    await worker.start()
    process = worker.process
    try:
        with pytest.raises(RuntimeError, match="^WORKER_DISCONNECTED$"):
            await asyncio.wait_for(worker.speech.infer(media()), 2)
        assert {m.status for m in worker.modules.values()} == {"unavailable"}
    finally:
        await worker.stop()
    gone(process.pid)
