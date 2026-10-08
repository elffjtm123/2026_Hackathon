import asyncio
import struct
from types import SimpleNamespace
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from tests.conftest import bearer


def send_v2(ws, event, sequence, session_id=None, data=None):
    ws.send_json(
        {
            "event": event,
            "version": 2,
            "sequence": sequence,
            "session_id": session_id,
            "timestamp_ms": 0,
            "module": "system",
            "level": "info",
            "data": data or {},
        }
    )


def test_v2_refuses_wrong_session_and_missing_envelope(client: TestClient) -> None:
    with client.websocket_connect("/api/v1/ws/practice-demo?protocol=2") as ws:
        send_v2(ws, "session.start", 1)
        assert ws.receive_json()["event"] == "session.ready"
        send_v2(ws, "calibration.start", 2, "00000000-0000-0000-0000-000000000000")
        assert ws.receive_json()["event"] == "error"
        ws.send_json({"event": "calibration.start"})
        assert ws.receive_json()["event"] == "error"


def test_v2_validation_and_audio_ack(client: TestClient) -> None:
    with client.websocket_connect("/api/v1/ws/practice-demo?protocol=2") as ws:
        send_v2(ws, "session.start", 1, data={"timeLimitSeconds": 0})
        assert ws.receive_json()["data"]["code"] == "INVALID_SETTINGS"
        send_v2(ws, "session.start", 2, data={"settings": {"gaze_enabled": False}})
        ready = ws.receive_json()
        assert ready["event"] == "session.ready" and ready["version"] == 2
        send_v2(ws, "calibration.start", 3, ready["session_id"])
        running = ws.receive_json()
        assert running["event"] == "session.running"
        origin = running["data"]["audio_origin_ms"]
        raw = struct.pack(">BBIQQI", 2, 2, 1, origin, 0, 8) + b"AB" * 8
        for _ in range(2):
            ws.send_bytes(raw)
            assert ws.receive_json()["data"]["accepted_sequence"] == 1
        ws.send_bytes(struct.pack(">BBIQQI", 2, 2, 3, origin, 0, 8) + b"AB" * 8)
        assert ws.receive_json()["data"]["code"] == "MEDIA_SEQUENCE_GAP"
        send_v2(ws, "session.end", 4, ready["session_id"])
        while True:
            event = ws.receive_json()
            if event["event"] == "session.completed":
                assert event["data"]["report"]["incomplete"] is True
                assert event["data"]["report"]["transcript"] is None
                break


def test_v2_epoch_timestamp_rejected(client: TestClient) -> None:
    with client.websocket_connect("/api/v1/ws/practice-demo?protocol=2") as ws:
        send_v2(ws, "session.start", 1)
        ready = ws.receive_json()
        send_v2(ws, "calibration.start", 2, ready["session_id"])
        ws.receive_json()
        ws.send_bytes(struct.pack(">BBIQQI", 2, 1, 1, 1_700_000_000_000, 0, 0) + b"jpeg")
        assert ws.receive_json()["data"]["code"] == "INVALID_MEDIA_TIMESTAMP"


def test_calibration_timeout_keeps_video_and_explicit_retry_available(client, monkeypatch):
    sleep = asyncio.sleep
    deadlines = 0

    async def fast_first_deadline(delay, *args, **kwargs):
        nonlocal deadlines
        if delay == 15:
            deadlines += 1
            if deadlines == 1:
                delay = 0.01
        return await sleep(delay, *args, **kwargs)

    monkeypatch.setattr(asyncio, "sleep", fast_first_deadline)
    with client.websocket_connect("/api/v1/ws/practice-demo?protocol=2") as ws:
        send_v2(ws, "session.start", 1)
        ready = ws.receive_json()
        send_v2(ws, "calibration.start", 2, ready["session_id"])
        assert ws.receive_json()["event"] == "session.calibrating"
        assert ws.receive_json()["data"]["code"] == "CALIBRATION_TIMEOUT"
        ws.send_bytes(struct.pack(">BBIQQI", 2, 1, 1, 200, 0, 0) + b"jpeg")
        observation = ws.receive_json()
        assert observation["event"] == "feedback"
        assert observation["data"]["metrics"]["recalibration_required"]
        send_v2(ws, "calibration.start", 3, ready["session_id"])
        assert ws.receive_json()["event"] == "session.calibrating"
        send_v2(ws, "session.end", 4, ready["session_id"])
        while ws.receive_json()["event"] != "session.completed":
            pass


def test_authenticated_v2_completion_uses_registered_pipeline(client, auth):
    session = create_session(client, auth)
    with client.websocket_connect(
        f"/api/v1/ws/sessions/{session['id']}?protocol=2&token={auth['access_token']}"
    ) as ws:
        send_v2(ws, "session.start", 1)
        ready = ws.receive_json()
        from uuid import UUID

        assert client.app.state.pipelines.get(UUID(session["id"])) is not None
        send_v2(ws, "session.end", 2, ready["session_id"])
        while ws.receive_json()["event"] != "session.completed":
            pass
    response = client.post(f"/api/v1/sessions/{session['id']}/complete", headers=bearer(auth))
    assert response.status_code == 200


@pytest.mark.parametrize("protocol", [1, 2])
def test_socket_closes_and_flushes_webrtc_before_pipeline_stop(client, auth, monkeypatch, protocol):
    session = create_session(client, auth)
    closed_while_running = []

    async def close(session_id):
        pipeline = client.app.state.pipelines.get(session_id)
        closed_while_running.append(bool(pipeline and pipeline.accepting))

    monkeypatch.setattr(client.app.state.webrtc, "close_session", close)
    with client.websocket_connect(
        f"/api/v1/ws/sessions/{session['id']}?protocol={protocol}&token={auth['access_token']}"
    ) as ws:
        if protocol == 2:
            send_v2(ws, "session.start", 1)
            ready = ws.receive_json()
            pipeline = client.app.state.pipelines.get(UUID(session["id"]))
            pipeline.analysis_settings["gaze_enabled"] = False
            send_v2(ws, "calibration.start", 2, ready["session_id"])
            assert ws.receive_json()["event"] == "session.running"
            send_v2(ws, "session.end", 3, ready["session_id"])
        else:
            ws.receive_json()
            ws.send_json({"event": "session.end"})
        while ws.receive_json()["event"] != "session.completed":
            pass
    assert closed_while_running and closed_while_running[0] is True


def create_session(client: TestClient, auth: dict[str, object]) -> dict[str, object]:
    response = client.post(
        "/api/v1/sessions",
        headers=bearer(auth),
        json={
            "type": "interview",
            "title": "백엔드 모의 면접",
            "settings": {
                "gaze_enabled": True,
                "speech_rate_enabled": True,
                "filler_words_enabled": True,
                "pronunciation_enabled": False,
            },
        },
    )
    assert response.status_code == 201
    return response.json()


@pytest.mark.parametrize("demo", [True, False])
def test_client_transcript_injection_is_rejected(client, auth, demo):
    session = create_session(client, auth)
    url = (
        "/api/v1/ws/practice-demo"
        if demo
        else f"/api/v1/ws/sessions/{session['id']}?token={auth['access_token']}"
    )
    with client.websocket_connect(url) as ws:
        if not demo:
            ws.receive_json()
        ws.send_json({"event": "transcript.final", "data": {"text": "invented transcript"}})
        ws.send_json({"event": "session.end"})
        error = ws.receive_json()
        last = error
        while last.get("type" if demo else "event") != "session.completed":
            last = ws.receive_json()
    if demo:
        assert error["type"] == "error"
    else:
        assert error["event"] == "error"
        assert error["data"]["code"] == "INVALID_MESSAGE"


def test_websocket_feedback_complete_and_report(
    client: TestClient, auth: dict[str, object]
) -> None:
    client.app.state.settings.max_realtime_messages_per_second = 100
    session = create_session(client, auth)
    with client.websocket_connect(
        f"/api/v1/ws/sessions/{session['id']}?token={auth['access_token']}"
    ) as websocket:
        ready = websocket.receive_json()
        assert ready["event"] == "session.ready"
        websocket.send_json({"event": "ping", "timestamp_ms": 10})
        assert websocket.receive_json()["event"] == "pong"

        for index in range(16):
            timestamp_ms = index * 125
            websocket.send_bytes(b"\x01" + timestamp_ms.to_bytes(8, "big") + b"jpeg")
            gaze_feedback = websocket.receive_json()
            assert gaze_feedback["event"] == "feedback"
            assert gaze_feedback["data"]["source"] == "gaze"

        for timestamp_ms in range(2000, 5501, 250):
            websocket.send_bytes(b"\x01" + timestamp_ms.to_bytes(8, "big") + b"jpeg")
            websocket.receive_json()
        websocket.send_bytes(b"\x01" + (6000).to_bytes(8, "big") + b"jpeg")
        away_feedback = websocket.receive_json()
        assert away_feedback["data"]["metrics"]["gaze_direction"] == "left"
        websocket.send_bytes(b"\x01" + (7500).to_bytes(8, "big") + b"jpeg")
        center_feedback = websocket.receive_json()
        assert center_feedback["data"]["metrics"]["gaze_direction"] == "center"

        # The test-only speech adapter supplies a known transcript for this media packet.
        websocket.send_bytes(
            b"\x02" + (1000).to_bytes(8, "big") + "음 저는 백엔드 개발자입니다".encode()
        )
        feedback = websocket.receive_json()
        assert feedback["event"] == "feedback"
        assert feedback["data"]["source"] == "speech_rate"
        transcript = websocket.receive_json()
        assert transcript["event"] == "transcript.final"
        websocket.send_json({"event": "session.end", "timestamp_ms": 1100, "data": {}})
        completed = websocket.receive_json()
        if completed["event"] == "feedback":
            completed = websocket.receive_json()
        assert completed["event"] == "session.completed"
        completion_report = completed["data"]["report"]
        assert completion_report["transcript"] == "음 저는 백엔드 개발자입니다"
        assert completion_report["filler_word_counts"] == {"음": 1}
        # This v1 fixture sends future frames and a 1500ms gap: neither is valid coverage.
        assert completion_report["gaze_away_duration_ms"] == 0
        assert (
            completion_report["gaze_metrics"]["valid_duration_ms"]
            <= completion_report["summary"]["duration_ms"]
        )
        assert completion_report["incomplete"] is False

    completed = client.post(f"/api/v1/sessions/{session['id']}/complete", headers=bearer(auth))
    assert completed.status_code == 200
    assert completed.json()["filler_word_counts"] == {"음": 1}
    report = client.get(f"/api/v1/sessions/{session['id']}/report", headers=bearer(auth))
    assert report.status_code == 200


def test_busy_model_refusal_releases_websocket_connection(client, auth):
    session = create_session(client, auth)
    client.app.state.gaze.gate = SimpleNamespace(busy=True)
    with client.websocket_connect(
        f"/api/v1/ws/sessions/{session['id']}?token={auth['access_token']}"
    ) as ws:
        with pytest.raises(WebSocketDisconnect) as error:
            ws.receive_json()
        assert error.value.code == 1013
    assert client.app.state.websocket_counts[UUID(session["id"])] == 0


def test_busy_model_refuses_webrtc_before_negotiation(client, auth):
    session = create_session(client, auth)
    client.app.state.gaze.gate = SimpleNamespace(busy=True)
    response = client.post(
        f"/api/v1/sessions/{session['id']}/webrtc/offer",
        headers=bearer(auth),
        json={"sdp": "v=0", "type": "offer"},
    )
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "MODEL_UNAVAILABLE_OR_BUSY"


def test_session_ownership_is_hidden(client: TestClient, auth: dict[str, object]) -> None:
    session = create_session(client, auth)
    other = client.post(
        "/api/v1/auth/register",
        json={
            "email": "other@example.com",
            "password": "other-password",
            "display_name": "다른 사람",
        },
    ).json()
    response = client.get(f"/api/v1/sessions/{session['id']}", headers=bearer(other))
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "SESSION_NOT_FOUND"
