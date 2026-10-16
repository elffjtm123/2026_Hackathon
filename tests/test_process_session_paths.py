import os
import sys

import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.main import create_app
from tests.conftest import bearer
from tests.test_session_flow import create_session, send_v2


@pytest.mark.parametrize("mode", ["demo-v2", "demo-v1", "auth-v2", "auth-v1", "webrtc"])
def test_native_worker_is_reaped_by_every_session_path(mode, monkeypatch, tmp_path):
    from app.ai.realtime_process import RealtimeModelProcess

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
        runtime = app.state.model_execution.runtime
        assert runtime.process is None
        auth = client.post(
            "/api/v1/auth/register",
            json={
                "email": "paths@example.com",
                "password": "correct-horse-battery-staple",
                "display_name": "test",
            },
        ).json()
        session = create_session(client, auth)
        if mode == "webrtc":
            response = client.post(
                f"/api/v1/sessions/{session['id']}/webrtc/offer",
                headers=bearer(auth),
                json={"sdp": "v=0", "type": "offer"},
            )
            assert response.status_code == 200
            assert runtime.process is not None
            child = runtime.process
            response = client.post(
                f"/api/v1/sessions/{session['id']}/complete", headers=bearer(auth)
            )
            assert response.status_code == 200
        else:
            url = (
                "/api/v1/ws/practice-demo"
                if mode.startswith("demo")
                else (f"/api/v1/ws/sessions/{session['id']}?token={auth['access_token']}")
            )
            v2 = mode.endswith("v2")
            if v2:
                url += "&protocol=2" if "?" in url else "?protocol=2"
            with client.websocket_connect(url) as ws:
                if v2:
                    send_v2(ws, "session.start", 1)
                    ready = ws.receive_json()
                    assert ready["event"] == "session.ready"
                    assert runtime.process is not None
                    child = runtime.process
                    send_v2(ws, "session.end", 2, ready["session_id"])
                else:
                    # Legacy demo has no mapped ready event; invalid input is a round-trip barrier.
                    if mode == "demo-v1":
                        ws.send_json({"event": "transcript.final", "data": {"text": "invalid"}})
                    ws.receive_json()
                    assert runtime.process is not None
                    child = runtime.process
                    ws.send_json({"event": "session.end"})
                event_key = "type" if mode == "demo-v1" else "event"
                while ws.receive_json().get(event_key, "") != "session.completed":
                    pass
        assert runtime.process is None
        assert child.returncode is not None
        assert app.state.model_execution.owner is None
        with pytest.raises(ProcessLookupError):
            os.kill(child.pid, 0)


def test_authenticated_legacy_disconnect_does_not_leave_models_resident(client, auth):
    session = create_session(client, auth)
    with client.websocket_connect(
        f"/api/v1/ws/sessions/{session['id']}?token={auth['access_token']}"
    ) as ws:
        assert ws.receive_json()["event"] == "session.ready"
    assert client.app.state.model_execution.owner is None
