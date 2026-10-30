import asyncio
import json
import os
import sqlite3
import subprocess
from pathlib import Path
from uuid import uuid4

from starlette.websockets import WebSocket

from app.realtime.pipeline import SessionPipeline
from app.services.session_service import safe_delivery_metrics
from tests.conftest import bearer
from tests.test_session_flow import send_v2


def run_session(
    client, auth, data=None, settings=None, follow_up=None, after_ready=False, events=None
):
    created = client.post(
        "/api/v1/sessions",
        headers=bearer(auth),
        json={
            "type": "presentation",
            "title": "전달력",
            "settings": {"gaze_enabled": False, **(settings or {})},
        },
    ).json()
    with client.websocket_connect(
        f"/api/v1/ws/sessions/{created['id']}?protocol=2&token={auth['access_token']}"
    ) as ws:
        send_v2(ws, "session.start", 1, data=data)
        sequence = 2
        if follow_up is not None and not after_ready:
            # Sent while the model is still preparing: the client does not know the id yet.
            send_v2(ws, "session.audio_settings", sequence, data=follow_up)
            sequence += 1
        ready = ws.receive_json()
        if follow_up is not None and after_ready:
            send_v2(ws, "session.audio_settings", sequence, ready["session_id"], follow_up)
            sequence += 1
        send_v2(ws, "session.end", sequence, ready["session_id"])
        while True:
            event = ws.receive_json()
            if events is not None:
                events.append(event)
            if event["event"] == "session.completed":
                break
    assert "delivery_metrics" not in event["data"]["report"]
    saved = client.post(f"/api/v1/sessions/{created['id']}/complete", headers=bearer(auth))
    assert saved.status_code == 200
    return created["id"], saved.json()


def test_stop_report_is_persisted_and_served_by_the_api(client, auth):
    session_id, saved = run_session(client, auth, {"audio_settings": {"autoGainControl": True}})
    metrics = saved["delivery_metrics"]
    assert metrics["status"] == "unavailable" and metrics["agc_on"] is True
    assert metrics["report"] is None and metrics["windows"] is None  # never reached running
    fetched = client.get(f"/api/v1/sessions/{session_id}/report", headers=bearer(auth)).json()
    assert fetched["delivery_metrics"] == metrics


def test_agc_must_be_a_bool_and_missing_is_null(client, auth):
    _, saved = run_session(client, auth, {"audio_settings": {"autoGainControl": "yes"}})
    assert saved["delivery_metrics"]["agc_on"] is None


def test_agc_may_arrive_after_session_start_before_ready(client, auth):
    follow_up = {"audio_settings": {"autoGainControl": False}}
    events = []
    _, saved = run_session(client, auth, follow_up=follow_up, events=events)
    assert saved["delivery_metrics"]["agc_on"] is False
    assert_clean_run(events)


def assert_clean_run(events):
    assert [e for e in events if e["event"] == "error"] == []
    assert events[-1]["data"]["report"]["incomplete"] is False


def test_agc_arriving_in_the_same_tick_as_prepare_finishing_is_handled_once(
    client, auth, monkeypatch
):
    gate = {}
    original_prepare = SessionPipeline.prepare
    original_receive = WebSocket.receive

    async def gated_prepare(self):
        await original_prepare(self)
        await gate.setdefault("open", asyncio.Event()).wait()

    async def receive(self, *args, **kwargs):
        message = await original_receive(self, *args, **kwargs)
        if "session.audio_settings" in (message.get("text") or ""):
            gate.setdefault("open", asyncio.Event()).set()
        return message

    monkeypatch.setattr(SessionPipeline, "prepare", gated_prepare)
    monkeypatch.setattr(WebSocket, "receive", receive)
    follow_up = {"audio_settings": {"autoGainControl": False}}
    events = []
    _, saved = run_session(client, auth, follow_up=follow_up, events=events)
    assert saved["delivery_metrics"]["agc_on"] is False
    assert_clean_run(events)


def test_only_the_last_audio_settings_during_prepare_is_applied_once(client, auth, monkeypatch):
    gate = {"seen": 0}
    applied = []
    original_prepare = SessionPipeline.prepare
    original_receive = WebSocket.receive
    original_set = SessionPipeline.set_audio_settings

    async def gated_prepare(self):
        await original_prepare(self)
        await gate.setdefault("open", asyncio.Event()).wait()

    async def receive(self, *args, **kwargs):
        message = await original_receive(self, *args, **kwargs)
        if "session.audio_settings" in (message.get("text") or ""):
            gate["seen"] += 1
            if gate["seen"] == 3:
                gate.setdefault("open", asyncio.Event()).set()
        return message

    def recording_set(self, raw):
        applied.append(raw)
        return original_set(self, raw)

    monkeypatch.setattr(SessionPipeline, "prepare", gated_prepare)
    monkeypatch.setattr(WebSocket, "receive", receive)
    monkeypatch.setattr(SessionPipeline, "set_audio_settings", recording_set)
    created = client.post(
        "/api/v1/sessions",
        headers=bearer(auth),
        json={"type": "presentation", "title": "t", "settings": {"gaze_enabled": False}},
    ).json()
    with client.websocket_connect(
        f"/api/v1/ws/sessions/{created['id']}?protocol=2&token={auth['access_token']}"
    ) as ws:
        send_v2(ws, "session.start", 1, data={"audio_settings": {"autoGainControl": True}})
        for sequence, agc in enumerate((True, True, False), start=2):
            send_v2(
                ws,
                "session.audio_settings",
                sequence,
                data={"audio_settings": {"autoGainControl": agc}},
            )
        ready = ws.receive_json()
        send_v2(ws, "session.end", 5, ready["session_id"])
        while ws.receive_json()["event"] != "session.completed":
            pass
    saved = client.post(f"/api/v1/sessions/{created['id']}/complete", headers=bearer(auth)).json()
    assert saved["delivery_metrics"]["agc_on"] is False
    # One call from session.start plus exactly one from the early buffer.
    assert applied == [{"autoGainControl": True}, {"autoGainControl": False}]


def test_audio_settings_after_a_failed_prepare_does_not_replace_the_real_error(client, auth):
    created = client.post(
        "/api/v1/sessions",
        headers=bearer(auth),
        json={"type": "presentation", "title": "t", "settings": {"gaze_enabled": False}},
    ).json()
    with client.websocket_connect(
        f"/api/v1/ws/sessions/{created['id']}?protocol=2&token={auth['access_token']}"
    ) as ws:
        send_v2(ws, "calibration.start", 1)
        first = ws.receive_json()
        assert first["event"] == "error" and first["data"]["code"] == "SESSION_NOT_READY"
        send_v2(ws, "session.audio_settings", 2, data={"audio_settings": {}})
        send_v2(ws, "ping", 3)
        following = ws.receive_json()
        assert following["event"] == "pong"


def test_agc_may_arrive_after_session_ready(client, auth):
    follow_up = {"audio_settings": {"autoGainControl": True}}
    _, saved = run_session(client, auth, follow_up=follow_up, after_ready=True)
    assert saved["delivery_metrics"]["agc_on"] is True


def test_invalid_late_agc_is_ignored_and_never_arriving_stays_null(client, auth):
    _, saved = run_session(client, auth, follow_up={"audio_settings": {"autoGainControl": "yes"}})
    assert saved["delivery_metrics"]["agc_on"] is None
    _, saved = run_session(client, auth)
    assert saved["delivery_metrics"]["agc_on"] is None


def test_toggle_off_persists_disabled(client, auth):
    _, saved = run_session(client, auth, settings={"delivery_enabled": False})
    assert saved["delivery_metrics"] == {"status": "disabled"}


def test_sanitiser_keeps_only_json_safe_values_and_caps_windows():
    windows = [{"start_ms": i, "pvq": float("nan"), "x": object(), "n": None} for i in range(800)]
    clean = safe_delivery_metrics(
        {
            "status": "observed",
            "agc_on": "yes",
            "report": {"sentences": [{"a": 1, "b": "text", "c": float("inf"), "d": {1, 2}}]},
            "windows": {"window_ms": 10_000, "baseline": {}, "windows": windows},
            "extra": "dropped",
        }
    )
    json.dumps(clean, allow_nan=False)
    assert clean["agc_on"] is None and "extra" not in clean
    assert len(clean["windows"]["windows"]) == 720
    assert clean["windows"]["windows"][0] == {"start_ms": 0, "pvq": None, "x": None, "n": None}
    assert clean["report"]["sentences"] == [{"a": 1, "b": "text", "c": None, "d": None}]


def test_sanitiser_handles_missing_or_bad_input():
    assert safe_delivery_metrics(None) == {}
    assert safe_delivery_metrics("x") == {}
    assert safe_delivery_metrics({"status": "disabled", "agc_on": True}) == {"status": "disabled"}
    assert safe_delivery_metrics({"status": "weird"})["status"] == "unavailable"
    failed = safe_delivery_metrics({"status": "failed", "agc_on": False, "report": None})
    assert failed == {"status": "failed", "agc_on": False, "report": None, "windows": None}


def test_delivery_metrics_migration_upgrades_old_rows_and_downgrades(tmp_path):
    root = Path(__file__).resolve().parents[1]
    database = tmp_path / "delivery.db"
    env = {**os.environ, "DATABASE_URL": f"sqlite+aiosqlite:///{database}"}

    def alembic(command, target):
        subprocess.run(
            [str(root / ".venv310/bin/python"), "-m", "alembic", command, target],
            cwd=root,
            env=env,
            check=True,
            capture_output=True,
        )

    alembic("upgrade", "0003_report_v2_integrity")
    with sqlite3.connect(database) as db:
        db.execute(
            "INSERT INTO session_reports (id, session_id, gaze_away_count, "
            "gaze_away_duration_ms, timeline, summary, gaze_metrics, speech_rate_metrics, "
            "pronunciation_metrics, script_sync_metrics, scoring_version) "
            "VALUES (?,?,0,0,'[]','{}','{}','{}','{}','{}','v2')",
            (uuid4().hex, uuid4().hex),
        )
        db.commit()
    alembic("upgrade", "head")
    with sqlite3.connect(database) as db:
        columns = {row[1]: row for row in db.execute("PRAGMA table_info(session_reports)")}
        assert columns["delivery_metrics"][3] == 1  # NOT NULL
        assert db.execute("SELECT delivery_metrics FROM session_reports").fetchone() == ("{}",)
    alembic("downgrade", "0003_report_v2_integrity")
    with sqlite3.connect(database) as db:
        columns = {row[1] for row in db.execute("PRAGMA table_info(session_reports)")}
        assert "delivery_metrics" not in columns
        assert db.execute("SELECT count(*) FROM session_reports").fetchone() == (1,)
