from app.realtime.pipeline import SessionPipeline
from tests.test_session_flow import send_v2


def test_local_demo_exposes_aggregates_only_after_completion(client, monkeypatch):
    monkeypatch.setattr(SessionPipeline, "_delivery_metrics", lambda self: {
        "status": "unavailable", "agc_on": False,
        "report": {"total_voiced_ms": 2000, "sentences": []},
        "windows": {"window_ms": 10000, "windows": []},
    })
    with client.websocket_connect("/api/v1/ws/practice-demo?protocol=2") as ws:
        send_v2(ws, "session.start", 1, data={"mode": "presentation", "settings": {"gaze_enabled": False}})
        ready = ws.receive_json()
        assert ready["event"] == "session.ready" and "delivery_metrics" not in ready["data"]
        send_v2(ws, "session.end", 2, ready["session_id"])
        while True:
            event = ws.receive_json()
            if event["event"] == "session.completed":
                break
            assert "delivery_metrics" not in event["data"]
        assert event["data"]["report"]["delivery_metrics"]["report"]["total_voiced_ms"] == 2000
