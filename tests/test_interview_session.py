"""Seam: the practice-demo WebSocket (protocol 2) running an interview with chosen questions."""

import json
import struct
import time
from uuid import UUID

import anyio
import pytest

from app.ai.base import AIResult
from app.modules.interview.plan import InterviewPlan
from app.modules.interview.questions import PlannedQuestion
from app.modules.speech.segments import SpeechSegmenter
from app.realtime.interview_run import InterviewRun
from tests.test_session_flow import send_v2

URL = "/api/v1/ws/practice-demo?protocol=2"
NO_GAZE = {"gaze_enabled": False}


def make_plan(client, count: int = 3) -> str:
    plan = InterviewPlan(
        questions=[
            PlannedQuestion(id=f"q{n}", kind="common", subtype="x", text=f"질문 {n} 입니다")
            for n in range(1, count + 1)
        ]
    )
    return client.app.state.interview_store.create(plan)


def start_data(interview_id: str, ids: list[str], **extra) -> dict:
    return {
        "mode": "interview",
        "settings": NO_GAZE,
        "interview": {"interview_id": interview_id, "question_ids": ids},
        **extra,
    }


def recv(ws, timeout: float = 5.0) -> dict:
    """`receive_json` that fails after `timeout` instead of hanging when an event is missing."""

    async def receive() -> dict:
        with anyio.fail_after(timeout):
            return await ws._send_rx.receive()

    try:
        message = ws.portal.call(receive)
    except TimeoutError:
        raise AssertionError(f"no event within {timeout} s") from None
    ws._raise_on_close(message)
    return json.loads(message["text"])


def until(ws, name: str, *, allow_error: bool = False) -> dict:
    for _ in range(60):
        event = recv(ws)
        if event["event"] == "error" and not allow_error:
            raise AssertionError(event)
        if event["event"] == name:
            return event
    raise AssertionError(f"missing {name}")


def begin(ws, data: dict) -> str:
    """session.start, then calibration (gaze off goes straight to running)."""
    send_v2(ws, "session.start", 1, data=data)
    session_id = until(ws, "session.ready")["session_id"]
    send_v2(ws, "calibration.start", 2, session_id)
    until(ws, "session.running")
    return session_id


def completed(ws) -> dict:
    return until(ws, "session.completed")["data"]["report"]


def start_error(client, data: dict) -> str:
    with client.websocket_connect(URL) as ws:
        send_v2(ws, "session.start", 1, data=data)
        return until(ws, "error", allow_error=True)["data"]["code"]


def test_start_with_questions_shows_the_first_chosen_question_when_running(client) -> None:
    interview_id = make_plan(client)
    with client.websocket_connect(URL) as ws:
        send_v2(ws, "session.start", 1, data=start_data(interview_id, ["q3", "q1"]))
        session_id = until(ws, "session.ready")["session_id"]
        send_v2(ws, "calibration.start", 2, session_id)
        until(ws, "session.running")
        question = until(ws, "interview.question")
        assert question["module"] == "system" and question["version"] == 2
        data = question["data"]
        assert (data["question_id"], data["round"], data["index"], data["total"]) == (
            "q3",
            1,
            1,
            2,
        )
        assert data["text"] == "질문 3 입니다"
        assert data["reading_ms"] == 3000 + round(len("질문 3 입니다") / 7 * 1000)
        assert data["answer_limit_ms"] == 120000 and data["replay_available"] is True
        send_v2(ws, "session.end", 3, session_id)
        completed(ws)


def test_no_question_is_shown_while_the_session_is_only_ready(client) -> None:
    interview_id = make_plan(client)
    with client.websocket_connect(URL) as ws:
        send_v2(ws, "session.start", 1, data=start_data(interview_id, ["q1"]))
        session_id = until(ws, "session.ready")["session_id"]
        send_v2(ws, "ping", 2, session_id)
        assert until(ws, "pong")
        send_v2(ws, "session.end", 3, session_id)
        names = []
        while True:
            event = recv(ws)
            names.append(event["event"])
            if event["event"] == "session.completed":
                break
        assert "interview.question" not in names


@pytest.mark.parametrize(
    "ids", [[], ["q1", "q1"], ["q1", "missing"]], ids=["empty", "duplicate", "not_in_plan"]
)
def test_bad_question_ids_are_invalid_settings_and_leave_the_plan_usable(client, ids) -> None:
    interview_id = make_plan(client)
    assert start_error(client, start_data(interview_id, ids)) == "INVALID_SETTINGS"
    with client.websocket_connect(URL) as ws:
        begin(ws, start_data(interview_id, ["q2"]))
        assert until(ws, "interview.question")["data"]["question_id"] == "q2"


def test_unknown_interview_id_is_not_found(client) -> None:
    assert start_error(client, start_data("nope", ["q1"])) == "INTERVIEW_NOT_FOUND"


def test_interview_field_needs_interview_mode(client) -> None:
    interview_id = make_plan(client)
    data = start_data(interview_id, ["q1"], mode="presentation")
    assert start_error(client, data) == "INVALID_SETTINGS"


def test_a_plan_cannot_start_a_second_session(client) -> None:
    interview_id = make_plan(client)
    with client.websocket_connect(URL) as ws:
        session_id = begin(ws, start_data(interview_id, ["q1"]))
        until(ws, "interview.question")
        send_v2(ws, "session.end", 3, session_id)
        completed(ws)
    # Even after the first session finished: one plan, one session.
    assert start_error(client, start_data(interview_id, ["q1"])) == "INTERVIEW_ALREADY_STARTED"


def test_a_failed_start_gives_the_plan_back(client, monkeypatch) -> None:
    from app.realtime.pipeline import SessionPipeline

    interview_id = make_plan(client)
    original = SessionPipeline.prepare

    async def unavailable(self):
        raise ValueError("MODEL_UNAVAILABLE_OR_BUSY")

    monkeypatch.setattr(SessionPipeline, "prepare", unavailable)
    assert start_error(client, start_data(interview_id, ["q1"])) == "MODEL_UNAVAILABLE_OR_BUSY"
    monkeypatch.setattr(SessionPipeline, "prepare", original)
    with client.websocket_connect(URL) as ws:
        begin(ws, start_data(interview_id, ["q1"]))
        assert until(ws, "interview.question")["data"]["question_id"] == "q1"


def test_questionless_interview_is_unchanged(client) -> None:
    with client.websocket_connect(URL) as ws:
        session_id = begin(ws, {"mode": "interview", "settings": NO_GAZE})
        send_v2(ws, "session.end", 3, session_id)
        names, report = [], None
        while True:
            event = recv(ws)
            names.append(event["event"])
            if event["event"] == "session.completed":
                report = event["data"]["report"]
                break
        assert not any(name.startswith("interview.") for name in names)
        assert "interview_items" not in report


def test_replay_while_the_question_is_on_screen_is_rejected(client) -> None:
    interview_id = make_plan(client)
    with client.websocket_connect(URL) as ws:
        session_id = begin(ws, start_data(interview_id, ["q1", "q2"]))
        until(ws, "interview.question")
        send_v2(ws, "interview.replay", 3, session_id, {"question_id": "q1"})
        assert until(ws, "interview.replay_rejected")["data"] == {"question_id": "q1"}
        send_v2(ws, "interview.replay", 4, session_id, {"question_id": "q2"})
        assert until(ws, "interview.replay_rejected")["data"] == {"question_id": "q2"}
        send_v2(ws, "session.end", 5, session_id)
        completed(ws)


def test_replay_needs_a_question_id_and_an_interview_with_questions(client) -> None:
    interview_id = make_plan(client)
    with client.websocket_connect(URL) as ws:
        session_id = begin(ws, start_data(interview_id, ["q1"]))
        send_v2(ws, "interview.replay", 3, session_id, {})
        assert until(ws, "error", allow_error=True)["data"]["code"] == "INVALID_SETTINGS"
    with client.websocket_connect(URL) as ws:
        session_id = begin(ws, {"mode": "interview", "settings": NO_GAZE})
        send_v2(ws, "interview.replay", 3, session_id, {"question_id": "q1"})
        assert until(ws, "error", allow_error=True)["data"]["code"] == "UNSUPPORTED_EVENT"


def test_session_end_reports_the_items_and_saves_them(client) -> None:
    interview_id = make_plan(client)
    with client.websocket_connect(URL) as ws:
        session_id = begin(ws, start_data(interview_id, ["q2", "q1"]))
        until(ws, "interview.question")
        time.sleep(0.05)
        send_v2(ws, "session.end", 3, session_id)
        names = []
        while True:
            event = recv(ws)
            names.append(event["event"])
            if event["event"] == "session.completed":
                report = event["data"]["report"]
                break
    assert names.index("interview.advanced") < names.index("session.completed")
    (item,) = report["interview_items"]
    assert (item["question_id"], item["round"], item["text"]) == ("q2", 1, "질문 2 입니다")
    assert item["advance_reason"] == "stopped" and item["replay_used"] is False
    assert item["answer_started_ms"] is None and item["transcript"] == ""
    assert item["utterances"] == []
    assert item["ended_ms"] >= item["shown_ms"] >= 0  # audio clock: equal in a short run
    saved = client.app.state.interview_store.get(interview_id)
    assert [i.question.id for i in saved.items] == ["q2"] and not saved.running


def test_audio_hides_the_question_and_its_transcript_lands_in_the_item(client, monkeypatch) -> None:
    monkeypatch.setattr(
        "app.realtime.pipeline.SpeechSegmenter",
        lambda *args, **kwargs: SpeechSegmenter(*args, **kwargs, is_speech=lambda *_: True),
    )

    class Talker:
        async def infer(self, media):
            return AIResult("speech_rate", media.timestamp_ms, "info", "ok", {}, "안녕하세요", True)

    monkeypatch.setattr("app.main.create_local_qwen_speech_adapter", lambda *_: Talker())
    interview_id = make_plan(client)
    with client.websocket_connect(URL) as ws:
        send_v2(ws, "session.start", 1, data=start_data(interview_id, ["q1", "q2"]))
        session_id = until(ws, "session.ready")["session_id"]
        send_v2(ws, "calibration.start", 2, session_id)
        origin = until(ws, "session.running")["data"]["audio_origin_ms"]
        until(ws, "interview.question")
        pcm = struct.pack("<h", 1000) * 3200
        seen = []  # events between the acks; the hide is one of them
        for sequence in range(1, 4):
            start = (sequence - 1) * 3200
            ws.send_bytes(
                struct.pack(">BBIQQI", 2, 2, sequence, origin + start // 16, start, 3200) + pcm
            )
            while (event := recv(ws))["event"] != "media.ack":
                seen.append(event)
        hidden = [e["data"] for e in seen if e["event"] == "interview.question_hidden"]
        assert hidden == [{"question_id": "q1"}]
        time.sleep(0.7)  # the session clock must pass the 600 ms of audio sent above
        send_v2(ws, "session.end", 3, session_id)
        report = completed(ws)
    (item,) = report["interview_items"]
    assert item["question_id"] == "q1" and item["advance_reason"] == "stopped"
    assert item["answer_started_ms"] == origin  # on the same clock as shown_ms
    assert item["shown_ms"] == origin
    assert item["transcript"] == "안녕하세요"
    (utterance,) = item["utterances"]
    assert utterance["start_ms"] == origin and utterance["text"] == "안녕하세요"


@pytest.fixture
def runs(monkeypatch) -> list[InterviewRun]:
    created: list[InterviewRun] = []

    class Recording(InterviewRun):
        def __init__(self, *args, **kwargs) -> None:
            super().__init__(*args, **kwargs)
            created.append(self)

    monkeypatch.setattr("app.api.v1.websocket.InterviewRun", Recording)
    return created


def sync(ws, session_id: str, sequence: int) -> None:
    """Round trip through the server's message loop: everything sent before it was handled."""
    send_v2(ws, "ping", sequence, session_id)
    until(ws, "pong")


def test_the_tick_task_ends_after_session_end(client, runs) -> None:
    interview_id = make_plan(client)
    with client.websocket_connect(URL) as ws:
        session_id = begin(ws, start_data(interview_id, ["q1"]))
        until(ws, "interview.question")
        sync(ws, session_id, 3)
        assert runs[0].running
        send_v2(ws, "session.end", 4, session_id)
        completed(ws)
    assert not runs[0].running


def test_the_tick_task_ends_and_items_are_saved_on_disconnect(client, runs) -> None:
    interview_id = make_plan(client)
    with client.websocket_connect(URL) as ws:
        session_id = begin(ws, start_data(interview_id, ["q1"]))
        until(ws, "interview.question")
        sync(ws, session_id, 3)
        assert runs[0].running
    assert not runs[0].running
    saved = client.app.state.interview_store.get(interview_id)
    assert [i.advance_reason for i in saved.items] == ["stopped"] and not saved.running
    assert not client.app.state.live_sessions


def test_the_tick_task_ends_and_items_are_saved_when_the_pipeline_stop_fails(
    client, runs, monkeypatch
) -> None:
    from app.realtime.pipeline import SessionPipeline

    original = SessionPipeline.stop

    async def failing_stop(self):
        await original(self)
        raise RuntimeError("test stop failure")

    interview_id = make_plan(client)
    monkeypatch.setattr(SessionPipeline, "stop", failing_stop)
    with pytest.raises(RuntimeError):
        with client.websocket_connect(URL) as ws:
            session_id = begin(ws, start_data(interview_id, ["q1"]))
            until(ws, "interview.question")
            send_v2(ws, "session.end", 3, session_id)
            completed(ws)
    assert not runs[0].running
    saved = client.app.state.interview_store.get(interview_id)
    assert len(saved.items) == 1 and not saved.running


def test_a_plan_is_not_used_up_when_the_session_never_started_running(client) -> None:
    interview_id = make_plan(client)
    with client.websocket_connect(URL) as ws:
        send_v2(ws, "session.start", 1, data=start_data(interview_id, ["q1"]))
        until(ws, "session.ready")  # ready, but the client never calibrates
    state = client.app.state.interview_store.get(interview_id)
    assert state.session_id is None and not state.running and state.items == []
    with client.websocket_connect(URL) as ws:
        begin(ws, start_data(interview_id, ["q2"]))
        assert until(ws, "interview.question")["data"]["question_id"] == "q2"


def test_authenticated_route_does_not_run_interview_questions(client, auth) -> None:
    from tests.test_session_flow import create_session

    interview_id = make_plan(client)
    session = create_session(client, auth)
    with client.websocket_connect(
        f"/api/v1/ws/sessions/{session['id']}?protocol=2&token={auth['access_token']}"
    ) as ws:
        send_v2(ws, "session.start", 1, data=start_data(interview_id, ["q1"]))
        assert until(ws, "error", allow_error=True)["data"]["code"] == "INVALID_SETTINGS"
    assert not client.app.state.interview_store.get(interview_id).running
    assert UUID(session["id"])
