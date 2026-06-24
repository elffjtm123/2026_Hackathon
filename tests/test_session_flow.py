from fastapi.testclient import TestClient

from tests.conftest import bearer


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
            },
        },
    )
    assert response.status_code == 201
    return response.json()


def test_websocket_feedback_complete_and_report(
    client: TestClient, auth: dict[str, object]
) -> None:
    session = create_session(client, auth)
    with client.websocket_connect(
        f"/api/v1/ws/sessions/{session['id']}?token={auth['access_token']}"
    ) as websocket:
        ready = websocket.receive_json()
        assert ready["event"] == "session.ready"
        websocket.send_json({"event": "ping", "timestamp_ms": 10})
        assert websocket.receive_json()["event"] == "pong"
        websocket.send_json(
            {
                "event": "transcript.final",
                "timestamp_ms": 1000,
                "data": {"text": "음 저는 백엔드 개발자입니다"},
            }
        )
        feedback = websocket.receive_json()
        assert feedback["event"] == "feedback"
        assert feedback["data"]["source"] == "speech_rate"
        transcript = websocket.receive_json()
        assert transcript["event"] == "transcript.final"

    completed = client.post(f"/api/v1/sessions/{session['id']}/complete", headers=bearer(auth))
    assert completed.status_code == 200
    assert completed.json()["filler_word_counts"] == {"음": 1}
    report = client.get(f"/api/v1/sessions/{session['id']}/report", headers=bearer(auth))
    assert report.status_code == 200


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


def test_demo_websocket_initializes_script_progress_from_start_message(
    client: TestClient,
) -> None:
    with client.websocket_connect("/api/v1/ws/practice-demo") as websocket:
        websocket.send_json(
            {
                "event": "session.start",
                "timestamp_ms": 0,
                "data": {
                    "mode": "presentation",
                    "script": "안녕하세요 오늘 서비스를 소개합니다",
                    "timeLimitSeconds": 60,
                    "settings": {
                        "karaokeGuideEnabled": True,
                        "styleTransferEnabled": False,
                    },
                },
            }
        )
        websocket.send_json(
            {
                "event": "transcript.final",
                "timestamp_ms": 1_000,
                "data": {"text": "안녕하세요 오늘 서비스를 소개합니다"},
            }
        )
        feedback = websocket.receive_json()
        assert feedback["type"] == "feedback"
        progress = websocket.receive_json()
        assert progress["type"] == "script.progress"
        assert progress["current_token_index"] >= 0
