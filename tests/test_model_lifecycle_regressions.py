import asyncio
import json
import sys
from uuid import UUID

import pytest
from fastapi.testclient import TestClient

from app.ai.realtime_process import RealtimeModelProcess
from app.core.config import Settings
from app.main import create_app
from tests.conftest import bearer
from tests.fake_ai import FakeSpeechAdapter
from tests.test_session_flow import create_session, send_v2

BAD_SDP = "\r\n".join(
    [
        "v=0",
        "o=- 0 0 IN IP4 127.0.0.1",
        "s=-",
        "t=0 0",
        "m=audio 9 UDP/TLS/RTP/SAVPF 0",
        "c=IN IP4 0.0.0.0",
        "a=mid:0",
        "a=sendonly",
        "a=rtpmap:0 PCMU/8000",
        "",
    ]
)


@pytest.fixture
def native_client(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "app.main.create_realtime_process",
        lambda settings: RealtimeModelProcess(
            settings, command=[sys.executable, "-m", "tests.model_worker_fixture"]
        ),
    )
    app = create_app(
        Settings(_env_file=None, database_url=f"sqlite+aiosqlite:///{tmp_path}/test.db")
    )
    with TestClient(app, client=("127.0.0.1", 50000)) as client:
        auth = client.post(
            "/api/v1/auth/register",
            json={
                "email": "regression@example.com",
                "password": "correct-horse-battery-staple",
                "display_name": "test",
            },
        ).json()
        yield client, auth


def test_rejected_duplicate_v2_cannot_stop_original_worker_or_peer(native_client):
    client, auth = native_client
    session = create_session(client, auth)
    url = f"/api/v1/ws/sessions/{session['id']}?token={auth['access_token']}&protocol=2"
    with client.websocket_connect(url) as first:
        send_v2(first, "session.start", 1)
        ready = first.receive_json()
        assert ready["event"] == "session.ready"
        runtime = client.app.state.model_execution.runtime
        child = runtime.process
        response = client.post(
            f"/api/v1/sessions/{session['id']}/webrtc/offer",
            headers=bearer(auth),
            json={"sdp": "v=0", "type": "offer"},
        )
        assert response.status_code == 200
        with client.websocket_connect(url) as rejected:
            send_v2(rejected, "session.start", 1)
            assert rejected.receive_json()["data"]["code"] == "SESSION_ALREADY_CONNECTED"
            send_v2(rejected, "session.end", 2)
            assert rejected.receive_json()["data"]["code"] == "SESSION_NOT_READY"
        assert runtime.process is child and child.returncode is None
        assert client.app.state.model_execution.owner == UUID(session["id"])
        assert UUID(session["id"]) in client.app.state.live_sessions
        assert client.app.state.webrtc.connections[UUID(session["id"])]
        send_v2(first, "session.end", 2, session["id"])
        while first.receive_json()["event"] != "session.completed":
            pass
        assert child.returncode is not None


@pytest.mark.parametrize("existing", [False, True])
def test_failed_webrtc_rolls_back_only_new_pipeline(native_client, existing):
    client, auth = native_client
    session = create_session(client, auth)
    endpoint = f"/api/v1/sessions/{session['id']}/webrtc/offer"
    if existing:
        assert (
            client.post(
                endpoint, headers=bearer(auth), json={"sdp": "v=0", "type": "offer"}
            ).status_code
            == 200
        )
    runtime = client.app.state.model_execution.runtime
    child = runtime.process
    old_peers = set(client.app.state.webrtc.connections.get(UUID(session["id"]), set()))
    response = client.post(endpoint, headers=bearer(auth), json={"sdp": BAD_SDP, "type": "offer"})
    assert response.status_code == 400
    assert client.app.state.webrtc.connections.get(UUID(session["id"]), set()) == old_peers
    if existing:
        assert runtime.process is child and child.returncode is None
        assert client.app.state.model_execution.owner == UUID(session["id"])
        client.post(f"/api/v1/sessions/{session['id']}/complete", headers=bearer(auth))
    else:
        assert runtime.process is None
        assert client.app.state.model_execution.owner is None
        assert not client.app.state.pipelines.pipelines


@pytest.mark.asyncio
@pytest.mark.parametrize("disconnect", [False, True])
@pytest.mark.parametrize("native", [False, True])
async def test_cold_start_can_be_cancelled_before_ready(client, monkeypatch, disconnect, native):
    entered = asyncio.Event()

    async def slow_start():
        entered.set()
        await asyncio.sleep(60)

    child = None
    if native:
        from app.ai.model_execution import ModelExecution

        runtime = RealtimeModelProcess(
            client.app.state.settings,
            command=[sys.executable, "-m", "tests.model_worker_fixture", "--slow-load"],
        )
        client.app.state.model_execution = ModelExecution(runtime)
        client.app.state.gaze, client.app.state.speech = runtime.gaze, runtime.speech
        client.app.state.module_status = runtime.modules
    else:
        runtime = client.app.state.model_execution.runtime
        monkeypatch.setattr(runtime, "start", slow_start)
    incoming, outgoing = asyncio.Queue(), asyncio.Queue()
    await incoming.put({"type": "websocket.connect"})
    scope = {
        "type": "websocket",
        "asgi": {"version": "3.0"},
        "scheme": "ws",
        "path": "/api/v1/ws/practice-demo",
        "raw_path": b"/api/v1/ws/practice-demo",
        "query_string": b"protocol=2",
        "headers": [(b"origin", b"http://testserver")],
        "client": ("127.0.0.1", 50000),
        "server": ("testserver", 80),
        "subprotocols": [],
    }
    task = asyncio.create_task(client.app(scope, incoming.get, outgoing.put))
    try:
        assert (await outgoing.get())["type"] == "websocket.accept"

        def control(event, sequence):
            return {
                "type": "websocket.receive",
                "text": json.dumps(
                    {
                        "event": event,
                        "version": 2,
                        "sequence": sequence,
                        "session_id": None,
                        "timestamp_ms": 0 if sequence == 1 else 999999,
                        "module": "system",
                        "level": "info",
                        "data": {},
                    }
                ),
            }

        await incoming.put(control("session.start", 1))
        if native:
            for _ in range(200):
                if runtime.process is not None:
                    break
                await asyncio.sleep(0.01)
            child = runtime.process
            assert child is not None and child.returncode is None
        else:
            await entered.wait()
        await incoming.put(
            {"type": "websocket.disconnect", "code": 1000}
            if disconnect
            else control("session.end", 2)
        )
        if not disconnect:

            async def completion():
                while True:
                    message = await outgoing.get()
                    if message["type"] == "websocket.send":
                        event = json.loads(message["text"])
                        if event["event"] == "session.completed":
                            return event

            report = await asyncio.wait_for(completion(), 8 if native else 1)
            assert report["data"]["report"]["incomplete"]
        await asyncio.wait_for(asyncio.shield(task), 8 if native else 1)
        assert client.app.state.model_execution.owner is None
        assert not client.app.state.live_sessions
        if native:
            assert runtime.process is None
            assert child.returncode is not None
            assert all(module.status == "idle" for module in runtime.modules.values())
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        if native:
            await runtime.stop()


def test_legacy_demo_retries_after_transient_loading_failure(client, monkeypatch):
    def fail(*args):
        raise RuntimeError("test load failure")

    monkeypatch.setattr("app.main.create_local_qwen_speech_adapter", fail)
    with client.websocket_connect("/api/v1/ws/practice-demo") as first:
        assert first.receive_json()["type"] == "error"
    calls = []

    def recovered(*args):
        calls.append(True)
        return FakeSpeechAdapter()

    monkeypatch.setattr("app.main.create_local_qwen_speech_adapter", recovered)
    with client.websocket_connect("/api/v1/ws/practice-demo") as retry:
        retry.send_json({"event": "transcript.final", "data": {"text": "invalid"}})
        event = retry.receive_json()
        assert calls == [True]
        assert "필수 AI 모델" not in event["message"]


def test_last_webrtc_peer_disconnect_reaps_worker_and_retains_report(native_client, monkeypatch):
    client, auth = native_client
    session = create_session(client, auth)
    identity = UUID(session["id"])
    response = client.post(
        f"/api/v1/sessions/{identity}/webrtc/offer",
        headers=bearer(auth),
        json={"sdp": "v=0", "type": "offer"},
    )
    assert response.status_code == 200
    pipeline = client.app.state.pipelines.get(identity)
    runtime = client.app.state.model_execution.runtime
    child = runtime.process
    original = pipeline.stop

    async def scenario():
        stopped = asyncio.Event()

        async def stop():
            result = await original()
            stopped.set()
            return result

        monkeypatch.setattr(pipeline, "stop", stop)
        peer = next(iter(client.app.state.webrtc.connections[identity]))
        await peer.close()
        await asyncio.wait_for(stopped.wait(), 2)

    client.portal.call(scenario)
    assert runtime.process is None and child.returncode is not None
    assert client.app.state.model_execution.owner is None
    response = client.post(f"/api/v1/sessions/{identity}/complete", headers=bearer(auth))
    assert response.status_code == 200
    assert response.json()["incomplete"]


def test_webrtc_cannot_attach_to_draining_pipeline(client, auth):
    session = create_session(client, auth)
    identity = UUID(session["id"])
    with client.websocket_connect(
        f"/api/v1/ws/sessions/{identity}?token={auth['access_token']}"
    ) as ws:
        assert ws.receive_json()["event"] == "session.ready"
        pipeline = client.app.state.pipelines.get(identity)
        pipeline.phase = "draining"
        response = client.post(
            f"/api/v1/sessions/{identity}/webrtc/offer",
            headers=bearer(auth),
            json={"sdp": "v=0", "type": "offer"},
        )
        assert response.status_code == 503
        assert client.app.state.model_execution.owner == identity


@pytest.mark.parametrize("delayed_close", [False, True])
def test_unconnected_webrtc_offer_expires_and_reaps_worker(
    native_client, monkeypatch, delayed_close
):
    client, auth = native_client
    monkeypatch.setattr("app.realtime.webrtc.CONNECT_TIMEOUT_SECONDS", 0.1, raising=False)
    runtime = client.app.state.model_execution.runtime
    stopped = asyncio.Event()
    original_stop = runtime.stop

    async def stop():
        await original_stop()
        stopped.set()

    monkeypatch.setattr(runtime, "stop", stop)
    session = create_session(client, auth)
    identity = UUID(session["id"])
    response = client.post(
        f"/api/v1/sessions/{identity}/webrtc/offer",
        headers=bearer(auth),
        json={"sdp": "v=0", "type": "offer"},
    )
    assert response.status_code == 200
    child = runtime.process

    async def scenario():
        peer = next(iter(client.app.state.webrtc.connections[identity]))
        original_close = peer.close
        closing = asyncio.get_running_loop().create_future()
        entered = False

        async def close():
            nonlocal entered
            if entered:
                await closing
                return
            entered = True
            await original_close()
            await asyncio.sleep(0.05)
            closing.set_result(None)

        if delayed_close:
            monkeypatch.setattr(peer, "close", close)
        try:
            await asyncio.wait_for(stopped.wait(), 2)
        finally:
            monkeypatch.setattr(peer, "close", original_close)
            if not closing.done():
                closing.set_result(None)

    client.portal.call(scenario)
    assert child.returncode is not None
    assert client.app.state.model_execution.owner is None
    assert not client.app.state.webrtc.connections.get(identity)
    assert client.app.state.pipelines.get(identity).incomplete


@pytest.mark.parametrize("existing", [False, True])
def test_abandoned_http_offer_settles_and_preserves_only_existing_session(
    native_client, monkeypatch, existing
):
    client, auth = native_client
    session = create_session(client, auth)
    identity = UUID(session["id"])
    endpoint = f"/api/v1/sessions/{identity}/webrtc/offer"
    if existing:
        assert (
            client.post(
                endpoint, headers=bearer(auth), json={"sdp": "v=0", "type": "offer"}
            ).status_code
            == 200
        )
    runtime = client.app.state.model_execution.runtime
    original_child = runtime.process

    async def scenario():
        entered = asyncio.Event()

        async def stalled(*args):
            entered.set()
            await asyncio.sleep(60)

        monkeypatch.setattr(client.app.state.webrtc, "create_answer", stalled)
        incoming, sent = asyncio.Queue(), []
        await incoming.put(
            {"type": "http.request", "body": json.dumps({"sdp": "v=0", "type": "offer"}).encode()}
        )
        scope = {
            "type": "http",
            "asgi": {"version": "3.0"},
            "http_version": "1.1",
            "method": "POST",
            "scheme": "http",
            "path": endpoint,
            "raw_path": endpoint.encode(),
            "query_string": b"",
            "headers": [
                (b"authorization", bearer(auth)["Authorization"].encode()),
                (b"content-type", b"application/json"),
            ],
            "client": ("127.0.0.1", 50000),
            "server": ("testserver", 80),
        }

        async def send(message):
            sent.append(message)

        task = asyncio.create_task(client.app(scope, incoming.get, send))
        try:
            await asyncio.wait_for(entered.wait(), 2)
            assert runtime.process is not None
            await incoming.put({"type": "http.disconnect"})
            await asyncio.wait_for(asyncio.shield(task), 2)
            assert sent[0]["status"] == 499
        finally:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    client.portal.call(scenario)
    if existing:
        assert runtime.process is original_child and original_child.returncode is None
        assert client.app.state.model_execution.owner == identity
    else:
        assert runtime.process is None
        assert client.app.state.model_execution.owner is None
        assert not client.app.state.pipelines.pipelines
