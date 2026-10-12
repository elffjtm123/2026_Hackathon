import asyncio
import importlib
import json
import os
import sys
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.core.errors import AppError
from tests.conftest import bearer
from tests.test_session_flow import create_session

ORIGIN = {"Origin": "http://testserver"}


def test_summary_rejects_empty_script(client: TestClient) -> None:
    response = client.post("/api/v1/scripts/summarize", headers=ORIGIN, json={"script": "  "})
    assert response.status_code == 422


def test_summary_requires_allowed_origin(client: TestClient) -> None:
    for headers in ({}, {"Origin": "https://evil.example"}):
        response = client.post(
            "/api/v1/scripts/summarize", headers=headers, json={"script": "서비스 소개."}
        )
        assert response.status_code == 403


def test_missing_summary_assets_is_error_not_fake_result(client: TestClient) -> None:
    client.app.state.settings.summary_model_path = "/definitely-missing-model.gguf"
    response = client.post(
        "/api/v1/scripts/summarize", headers=ORIGIN, json={"script": "서비스 소개."}
    )
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "SUMMARY_UNAVAILABLE"
    assert "sentences" not in response.json()


def test_summary_is_blocked_while_practicing(client: TestClient) -> None:
    client.app.state.live_sessions.add("test-session")
    response = client.post(
        "/api/v1/scripts/summarize", headers=ORIGIN, json={"script": "서비스 소개."}
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "PRACTICE_ACTIVE"


@pytest.fixture
def native_assets(tmp_path: Path) -> tuple[Path, Path, Path]:
    # Test-only native HTTP boundary; exercise actual spawning and termination, not an LLM.
    executable = tmp_path / "summary-server"
    pid_file = tmp_path / "pid"
    executable.write_text(
        f"#!{sys.executable}\n"
        "import json, os, sys, time\n"
        "from http.server import BaseHTTPRequestHandler, HTTPServer\n"
        f"open({str(pid_file)!r}, 'w').write(str(os.getpid()))\n"
        "class Handler(BaseHTTPRequestHandler):\n"
        " def log_message(self, *args): pass\n"
        " def do_GET(self):\n"
        '  self.send_response(200); self.end_headers(); self.wfile.write(b\'{"status":"ok"}\')\n'
        " def do_POST(self):\n"
        "  data=json.loads(self.rfile.read(int(self.headers['Content-Length'])))\n"
        "  content=data['messages'][0]['content']\n"
        "  text=content.split('<발표문>\\n',1)[1].split('\\n</발표문>',1)[0]\n"
        "  if '대기' in text: time.sleep(5)\n"
        "  reason='length' if '실패' in text else 'stop'\n"
        "  result={'choices':[{'message':{'content':'요약: '+text},'finish_reason':reason}]}\n"
        "  self.send_response(200); self.end_headers()\n"
        "  self.wfile.write(json.dumps(result).encode())\n"
        "HTTPServer(('127.0.0.1',int(sys.argv[sys.argv.index('--port')+1])),Handler).serve_forever()\n"
    )
    executable.chmod(0o700)
    model = tmp_path / "model.gguf"
    model.write_bytes(b"test-only boundary fixture")
    return executable, model, pid_file


def summarizer(assets: tuple[Path, Path, Path], timeout: float = 10):
    spec = importlib.util.find_spec("app.ai.script_summary")
    assert spec is not None, "local summary implementation missing"
    module = importlib.import_module("app.ai.script_summary")
    return module.LocalScriptSummarizer(
        Settings(
            _env_file=None,
            summary_server_path=str(assets[0]),
            summary_model_path=str(assets[1]),
            summary_timeout_seconds=timeout,
        )
    )


def assert_process_gone(pid_file: Path) -> None:
    with pytest.raises(ProcessLookupError):
        os.kill(int(pid_file.read_text()), 0)


@pytest.mark.asyncio
async def test_summary_preserves_sentence_ids_and_process_exits(native_assets) -> None:
    service = summarizer(native_assets)
    result = await service.summarize("  같은 문장.\n같은 문장. 마지막 부분  ")
    assert result["normalized_script"] == "같은 문장. 같은 문장. 마지막 부분"
    assert result["sentences"] == [
        {"sentence_index": 0, "original": "같은 문장.", "hint": "요약: 같은 문장.", "error": None},
        {"sentence_index": 1, "original": "같은 문장.", "hint": "요약: 같은 문장.", "error": None},
        {
            "sentence_index": 2,
            "original": "마지막 부분",
            "hint": "요약: 마지막 부분",
            "error": None,
        },
    ]
    assert not service.busy
    assert_process_gone(native_assets[2])


@pytest.mark.asyncio
async def test_truncated_generation_is_not_a_valid_hint(native_assets) -> None:
    service = summarizer(native_assets)
    result = await service.summarize("정상 문장. 실패 문장.")
    assert result["sentences"][0]["hint"] == "요약: 정상 문장."
    assert result["sentences"][1]["hint"] is None
    assert result["sentences"][1]["error"]
    assert_process_gone(native_assets[2])


@pytest.mark.asyncio
async def test_timeout_kills_model_before_unlocking(native_assets) -> None:
    service = summarizer(native_assets, timeout=0.8)
    with pytest.raises(AppError) as failure:
        await service.summarize("대기 문장.")
    assert failure.value.code == "SUMMARY_TIMEOUT"
    assert not service.busy
    assert_process_gone(native_assets[2])


@pytest.mark.asyncio
async def test_cancel_and_double_submission_do_not_leave_model_running(native_assets) -> None:
    service = summarizer(native_assets)
    task = asyncio.create_task(service.summarize("대기 문장."))
    for _ in range(100):
        if native_assets[2].exists():
            break
        await asyncio.sleep(0.01)
    assert service.busy
    with pytest.raises(AppError) as failure:
        await service.summarize("다른 문장.")
    assert failure.value.code == "SUMMARY_BUSY"
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert not service.busy
    assert_process_gone(native_assets[2])


@pytest.mark.asyncio
async def test_cancellation_during_spawn_still_reaps_child(native_assets, monkeypatch) -> None:
    service = summarizer(native_assets)
    original = asyncio.create_subprocess_exec
    spawned = asyncio.Event()
    children = []

    async def slow_spawn(*args, **kwargs):
        child = await original(*args, **kwargs)
        children.append(child)
        spawned.set()
        await asyncio.sleep(0.2)
        return child

    monkeypatch.setattr(asyncio, "create_subprocess_exec", slow_spawn)
    task = asyncio.create_task(service.summarize("정상 문장."))
    await spawned.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    try:
        with pytest.raises(ProcessLookupError):
            os.kill(children[0].pid, 0)
    finally:
        if children[0].returncode is None:
            children[0].terminate()
            await children[0].wait()


@pytest.mark.asyncio
async def test_repeated_cancellation_before_spawn_handle_cannot_orphan_child(
    native_assets, monkeypatch
):
    service = summarizer(native_assets)
    original = asyncio.create_subprocess_exec
    spawned = asyncio.Event()
    children = []

    async def slow_spawn(*args, **kwargs):
        child = await original(*args, **kwargs)
        children.append(child)
        spawned.set()
        await asyncio.sleep(0.2)
        return child

    monkeypatch.setattr(asyncio, "create_subprocess_exec", slow_spawn)
    task = asyncio.create_task(service.summarize("정상 문장."))
    try:
        await spawned.wait()
        for _ in range(3):
            task.cancel()
            await asyncio.sleep(0.02)
        with pytest.raises(asyncio.CancelledError):
            await task
        assert children[0].returncode is not None, "child still alive before handle delivery"
        assert not service.busy
    finally:
        await asyncio.sleep(0.25)
        if children[0].returncode is None:
            children[0].kill()
            await children[0].wait()


def test_summary_blocks_session_start_until_model_exit(client: TestClient) -> None:
    client.app.state.script_summarizer.busy = True
    with client.websocket_connect("/api/v1/ws/practice-demo?protocol=2", headers=ORIGIN) as ws:
        ws.send_json(
            {
                "event": "session.start",
                "version": 2,
                "sequence": 1,
                "session_id": None,
                "timestamp_ms": 0,
                "module": "system",
                "level": "info",
                "data": {"mode": "presentation"},
            }
        )
        event = ws.receive_json()
        assert event["event"] == "error" and event["data"]["code"] == "SUMMARY_BUSY"
    client.app.state.script_summarizer.busy = False


@pytest.mark.asyncio
async def test_disconnect_through_http_middleware_stops_summary(client, native_assets) -> None:
    service = summarizer(native_assets)
    client.app.state.script_summarizer = service
    messages = asyncio.Queue()
    await messages.put(
        {"type": "http.request", "body": json.dumps({"script": "대기 문장."}).encode()}
    )
    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "POST",
        "scheme": "http",
        "path": "/api/v1/scripts/summarize",
        "raw_path": b"/api/v1/scripts/summarize",
        "query_string": b"",
        "headers": [(b"content-type", b"application/json"), (b"origin", b"http://testserver")],
        "client": ("127.0.0.1", 50000),
        "server": ("testserver", 80),
    }

    sent = []

    async def send(message):
        sent.append(message)

    task = asyncio.create_task(client.app(scope, messages.get, send))
    try:
        for _ in range(200):
            if native_assets[2].exists():
                break
            await asyncio.sleep(0.01)
        assert service.busy
        await messages.put({"type": "http.disconnect"})
        for _ in range(200):
            if not service.busy:
                break
            await asyncio.sleep(0.01)
        assert not service.busy, "HTTP disconnect did not cancel inference"
        assert_process_gone(native_assets[2])
        await asyncio.wait_for(task, timeout=2)
        assert sent[0]["status"] == 499
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        await service.close()


@pytest.mark.asyncio
async def test_repeated_cancellation_cannot_unlock_with_live_child(
    native_assets, monkeypatch
) -> None:
    service = summarizer(native_assets)
    started = asyncio.Event()
    stopping = asyncio.Event()
    child = None

    async def run(sentences):
        nonlocal child
        child = await asyncio.create_subprocess_exec(
            sys.executable,
            "-c",
            "import signal,time; signal.signal(signal.SIGTERM,signal.SIG_IGN); "
            "print('ready',flush=True); time.sleep(60)",
            stdout=asyncio.subprocess.PIPE,
        )
        service._process = child
        await child.stdout.readline()
        started.set()
        await asyncio.sleep(60)

    original_stop = service._stop

    async def stop():
        stopping.set()
        await original_stop()

    monkeypatch.setattr(service, "_run", run)
    monkeypatch.setattr(service, "_stop", stop)
    task = asyncio.create_task(service.summarize("대기 문장."))
    try:
        await started.wait()
        task.cancel()
        await stopping.wait()
        for _ in range(3):
            task.cancel()
            await asyncio.sleep(0.02)
        with pytest.raises(asyncio.CancelledError):
            await task
        assert not service.busy
        assert child.returncode is not None, "gate released while child still alive"
    finally:
        if child is not None and child.returncode is None:
            child.kill()
            await child.wait()


def test_legacy_demo_blocks_start_while_summarizing(client):
    client.app.state.script_summarizer.busy = True
    try:
        with client.websocket_connect("/api/v1/ws/practice-demo", headers=ORIGIN) as ws:
            ws.send_json({"event": "transcript.final", "data": {"text": "invalid"}})
            event = ws.receive_json()
            assert event["type"] == "error" and "요약" in event["message"]
    finally:
        client.app.state.script_summarizer.busy = False


def test_legacy_demo_blocks_summary_while_running(client):
    with client.websocket_connect("/api/v1/ws/practice-demo", headers=ORIGIN):
        response = client.post(
            "/api/v1/scripts/summarize", headers=ORIGIN, json={"script": "서비스 소개."}
        )
        assert response.status_code == 409
        assert response.json()["error"]["code"] == "PRACTICE_ACTIVE"
    assert not client.app.state.live_sessions


def test_webrtc_cannot_start_while_summarizing(client, auth):
    session = create_session(client, auth)
    client.app.state.script_summarizer.busy = True
    try:
        response = client.post(
            f"/api/v1/sessions/{session['id']}/webrtc/offer",
            headers=bearer(auth),
            json={"sdp": "v=0", "type": "offer"},
        )
        assert response.status_code == 409
        assert response.json()["error"]["code"] == "SUMMARY_BUSY"
        assert not client.app.state.pipelines.pipelines
    finally:
        client.app.state.script_summarizer.busy = False


def test_authenticated_legacy_ws_cannot_start_while_summarizing(client, auth):
    from starlette.websockets import WebSocketDisconnect

    session = create_session(client, auth)
    client.app.state.script_summarizer.busy = True
    try:
        with client.websocket_connect(
            f"/api/v1/ws/sessions/{session['id']}?token={auth['access_token']}"
        ) as ws:
            with pytest.raises(WebSocketDisconnect) as closed:
                ws.receive_json()
            assert closed.value.code == 1013
        assert not client.app.state.pipelines.pipelines
    finally:
        client.app.state.script_summarizer.busy = False


@pytest.mark.parametrize("protocol", [1, 2])
def test_failed_prepare_and_rollback_do_not_poison_session_retry(client, monkeypatch, protocol):
    async def scenario():
        registry = client.app.state.pipelines
        session_id = uuid4()
        original = registry.state_store.set

        async def unavailable(*args):
            raise OSError("state store unavailable")

        monkeypatch.setattr(registry.state_store, "set", unavailable)
        try:
            with pytest.raises(OSError):
                await registry.get_or_create(session_id, {}, protocol=protocol)
        finally:
            monkeypatch.setattr(registry.state_store, "set", original)
        assert registry.get(session_id) is None, "failed pipeline retained after rollback error"
        recovered = await registry.get_or_create(session_id, {}, protocol=protocol)
        assert recovered.running and recovered.phase != "completed"
        await registry.stop(session_id)

    client.portal.call(scenario)
