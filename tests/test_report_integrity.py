import json
import os
import sqlite3
import subprocess
from pathlib import Path
from uuid import uuid4

from app.realtime.aggregator import FeedbackAggregator
from tests.conftest import bearer
from tests.test_gaze_service import gaze_result


def test_empty_report_is_not_a_perfect_score_or_observed_zero():
    report = FeedbackAggregator().report(running_started_ms=0, end_ms=0)
    assert report["overall_score"] is None
    assert report["gaze_metrics"]["coverage_ratio"] is None
    assert report["average_syllables_per_minute"] is None
    assert report["filler_word_counts"] is None
    assert report["speech_rate_metrics"]["status"] == "unavailable"


def test_no_alignment_evidence_is_not_measured_zero():
    report = FeedbackAggregator().report(0, 5000, settings={"script": "안녕하세요."})
    assert report["script_completion_ratio"] is None
    assert report["script_sync_metrics"]["completion_ratio"] is None
    assert report["script_sync_metrics"]["status"] == "unavailable"


def test_gaze_coverage_is_time_weighted_not_frame_count():
    reports = []
    for interval in [125, 500]:
        aggregator = FeedbackAggregator()
        for timestamp in range(0, 2001, interval):
            aggregator.add(gaze_result(timestamp, True, "left" if timestamp < 1000 else "center"))
        reports.append(aggregator.report(running_started_ms=0, end_ms=2000)["gaze_metrics"])
    assert reports[0] == reports[1]
    assert reports[0]["away_ratio"] == 0.5
    assert reports[0]["coverage_ratio"] == 1


def test_long_gap_and_initial_and_stale_tail_are_unknown():
    aggregator = FeedbackAggregator()
    aggregator.add(gaze_result(1000, True, "left"))
    aggregator.add(gaze_result(3000, True, "center"))
    report = aggregator.report(running_started_ms=0, end_ms=4500)
    gaze = report["gaze_metrics"]
    assert gaze["away_duration_ms"] == 0
    assert gaze["valid_duration_ms"] == 1000
    assert gaze["unknown_duration_ms"] == 3500
    assert gaze["away_ratio"] == 0
    short = aggregator.report(running_started_ms=0, end_ms=3250)["gaze_metrics"]
    assert short["valid_duration_ms"] == 250


def test_disabled_report_does_not_look_like_zero_detections():
    report = FeedbackAggregator().report(
        0,
        1000,
        settings={
            "gaze_enabled": False,
            "speech_rate_enabled": False,
            "filler_words_enabled": False,
        },
    )
    assert report["gaze_metrics"]["status"] == "disabled"
    assert report["speech_rate_metrics"]["status"] == "disabled"
    assert report["filler_word_counts"] is None


def test_new_persisted_report_contains_no_nested_source_text(client, auth):
    from app.ai.base import AIResult
    from tests.test_session_flow import send_v2

    created = client.post(
        "/api/v1/sessions",
        headers=bearer(auth),
        json={
            "type": "presentation",
            "title": "집계 검증",
            "script": "시스템 기능을 소개합니다.",
            "time_limit_seconds": 60,
            "settings": {"gaze_enabled": False},
        },
    ).json()
    with client.websocket_connect(
        f"/api/v1/ws/sessions/{created['id']}?protocol=2&token={auth['access_token']}"
    ) as ws:
        send_v2(ws, "session.start", 1)
        ready = ws.receive_json()
        pipeline = client.app.state.pipelines.get(__import__("uuid").UUID(created["id"]))
        private = "비공개테스트원문"
        pipeline.aggregator.add(
            AIResult(
                "speech_rate",
                100,
                "info",
                "",
                {
                    "utterance_id": "u",
                    "syllable_count": 8,
                    "voiced_ms": 1000,
                    "filler_counts": {"음": 1},
                    "recognized": private,
                    "nested": {"expected": private},
                },
                private,
                True,
            )
        )
        pipeline.aggregator.add_pronunciation(
            {
                "pronunciation_clarity_score": 85,
                "expected": private,
                "recognized": private,
                "difficult_units": [{"expected": private}],
            },
            100,
        )
        pipeline.incomplete = True
        send_v2(ws, "session.end", 2, ready["session_id"])
        while ws.receive_json()["event"] != "session.completed":
            pass
    saved = client.post(f"/api/v1/sessions/{created['id']}/complete", headers=bearer(auth))
    assert saved.status_code == 200
    data = saved.json()
    assert data["incomplete"] is True
    assert data["transcript"] is None
    assert private not in json.dumps(data, ensure_ascii=False)
    assert data["average_syllables_per_minute"] == 480
    assert data["filler_word_counts"] == {"음": 1}


def test_old_report_survives_nullable_migration(tmp_path):
    root = Path(__file__).resolve().parents[1]
    database = tmp_path / "migration.db"
    env = {**os.environ, "DATABASE_URL": f"sqlite+aiosqlite:///{database}"}
    command = [str(root / ".venv310/bin/python"), "-m", "alembic", "upgrade"]
    subprocess.run(
        [*command, "0002_scripts_and_modular_reports"],
        cwd=root,
        env=env,
        check=True,
        capture_output=True,
    )
    with sqlite3.connect(database) as db:
        sid = uuid4().hex
        db.execute(
            "INSERT INTO session_reports (id, session_id, overall_score, gaze_score, "
            "speech_rate_score, filler_word_score, gaze_away_count, gaze_away_duration_ms, "
            "average_syllables_per_minute, filler_word_counts, transcript, timeline, summary, "
            "gaze_metrics, speech_rate_metrics, pronunciation_metrics, script_sync_metrics, "
            "scoring_version) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                uuid4().hex,
                sid,
                90,
                80,
                85,
                100,
                1,
                200,
                300,
                "{}",
                "과거 전사",
                "[]",
                "{}",
                "{}",
                "{}",
                "{}",
                "{}",
                "v1",
            ),
        )
        db.commit()
    subprocess.run([*command, "head"], cwd=root, env=env, check=True, capture_output=True)
    with sqlite3.connect(database) as db:
        assert db.execute(
            "SELECT overall_score,transcript,scoring_version,incomplete FROM session_reports"
        ).fetchone() == (90, "과거 전사", "v1", 0)
        columns = {row[1]: row[3] for row in db.execute("PRAGMA table_info(session_reports)")}
        assert columns["overall_score"] == 0


def test_legacy_auto_created_style_table_is_not_destroyed_on_upgrade(tmp_path):
    root = Path(__file__).resolve().parents[1]
    database = tmp_path / "legacy.db"
    env = {**os.environ, "DATABASE_URL": f"sqlite+aiosqlite:///{database}"}
    command = [str(root / ".venv310/bin/python"), "-m", "alembic", "upgrade"]
    subprocess.run([*command, "0001_initial"], cwd=root, env=env, check=True, capture_output=True)
    with sqlite3.connect(database) as db:
        db.execute("CREATE TABLE style_transfer_jobs (id TEXT PRIMARY KEY, source_script TEXT)")
        db.execute("INSERT INTO style_transfer_jobs VALUES ('legacy','과거 자료')")
        db.commit()
    result = subprocess.run([*command, "head"], cwd=root, env=env, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    with sqlite3.connect(database) as db:
        assert db.execute("SELECT source_script FROM style_transfer_jobs").fetchone() == (
            "과거 자료",
        )
