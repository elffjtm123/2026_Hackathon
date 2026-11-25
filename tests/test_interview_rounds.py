"""Seam: the practice-demo WebSocket running both interview rounds (round break) with fakes."""

import asyncio
import struct
import time

import pytest

from app.ai.base import AIResult
from app.modules.interview.composition import TurnRules
from app.modules.interview.plan import InterviewPlan
from app.modules.interview.questions import PlannedQuestion, RubricItem
from app.modules.speech.segments import SpeechSegmenter
from tests.test_interview_follow_ups import reply
from tests.test_interview_llm import FakeLlm, FakeSession
from tests.test_interview_session import URL, completed, recv, start_data, until
from tests.test_session_flow import send_v2

LOUD = struct.pack("<h", 1000)
QUIET = b"\0\0"
ANSWER = "제가 검출 모델을 학습시키고 서버에 올려서 성능을 확인했고 결과가 좋았습니다"
FAST = TurnRules(
    reading_base_ms=100,
    reading_chars_per_second=1000,
    silence_ms=400,
    min_answer_ms=100,
    no_response_ms=4000,
    final_wait_cap_ms=500,
    stall_allowance_ms=200,
)


class BlockingSession(FakeSession):
    """Never answers; `calls` shows that generation started."""

    async def complete_json(self, prompt, schema, **kwargs):
        self.calls.append(("follow_up", prompt))
        await asyncio.Event().wait()


@pytest.fixture
def fast(client, monkeypatch) -> None:
    monkeypatch.setattr("app.api.v1.websocket.TurnRules", lambda: FAST)
    monkeypatch.setattr(
        "app.realtime.pipeline.SpeechSegmenter",
        lambda *args, **kwargs: SpeechSegmenter(
            *args, **kwargs, is_speech=lambda pcm: struct.unpack_from("<h", pcm)[0] > 0
        ),
    )

    class Talker:
        async def infer(self, media):
            return AIResult("speech_rate", media.timestamp_ms, "info", "ok", {}, ANSWER, True)

    monkeypatch.setattr("app.main.create_local_qwen_speech_adapter", lambda *_: Talker())


def make_plan(client, count: int = 1) -> str:
    plan = InterviewPlan(
        questions=[
            PlannedQuestion(
                id=f"q{n}",
                kind="document",
                subtype="experience",
                text=f"질문 {n} 입니다",
                rubric_items=[
                    RubricItem.SPECIFICITY,
                    RubricItem.REASONING,
                    RubricItem.LEARNING,
                ],
            )
            for n in range(1, count + 1)
        ]
    )
    return client.app.state.interview_store.create(plan)


def use_llm(client, session: FakeSession) -> FakeLlm:
    llm = FakeLlm(session)
    client.app.state.local_llm = llm
    return llm


def speak(ws, origin: int, sequence: int, start: int) -> None:
    """500 ms of voice and 500 ms of silence; the answer ends by silence."""
    for n, pcm in enumerate((LOUD * 8000, QUIET * 8000)):
        at = start + n * 8000
        ws.send_bytes(struct.pack(">BBIQQI", 2, 2, sequence + n, origin + at // 16, at, 8000) + pcm)


def drain_until(ws, name: str, seen: list[dict]) -> dict:
    for _ in range(200):
        event = recv(ws)
        seen.append(event)
        if event["event"] == "error":
            raise AssertionError(event)
        if event["event"] == name:
            return event
    raise AssertionError(f"missing {name}")


def test_both_rounds_run_in_one_session_with_the_break_between(client, fast) -> None:
    interview_id = make_plan(client)
    session = FakeSession({"follow_up": reply("reasoning", question="그 서버 구성을 택한 이유는?")})
    llm = use_llm(client, session)
    with client.websocket_connect(URL) as ws:
        send_v2(ws, "session.start", 1, data=start_data(interview_id, ["q1"]))
        session_id = until(ws, "session.ready")["session_id"]
        send_v2(ws, "calibration.start", 2, session_id)
        origin = until(ws, "session.running")["data"]["audio_origin_ms"]
        until(ws, "interview.question")
        speak(ws, origin, 1, 0)
        seen: list[dict] = []
        second = drain_until(ws, "interview.question", seen)
        names = [e["event"] for e in seen]
        breaks = [e["data"] for e in seen if e["event"] == "interview.round_break"]
        assert breaks == [
            {"stage": "suspending"},
            {"stage": "generating"},
            {"stage": "resuming", "follow_up_count": 1},
        ]
        order = [
            n
            for n in names
            if n in {"interview.advanced", "interview.round_break", "session.suspended"}
            or n == "session.resumed"
        ]
        assert order == [
            "interview.advanced",
            "interview.round_break",
            "session.suspended",
            "interview.round_break",
            "interview.round_break",
            "session.resumed",
        ]
        assert "interview.finished" not in names
        assert second["data"]["question_id"] == "q1-f" and second["data"]["round"] == 2
        assert second["data"]["text"] == "그 서버 구성을 택한 이유는?"
        assert llm.entered == 1 and llm.exited == 1  # the generation model was reaped
        # The client was not told to stop: the audio timeline is the same one and the first
        # audio after the break may skip ahead.
        resumed = next(e for e in seen if e["event"] == "session.resumed")
        assert resumed["data"]["audio_origin_ms"] == origin
        # Everything above ran faster than real time (the test sends a second of audio at
        # once), so let the session clock catch up before skipping 1 s ahead and two sequence
        # numbers, as a client that paused sending would.
        time.sleep(2)
        speak(ws, origin, 5, 32000)
        tail: list[dict] = []
        drain_until(ws, "interview.finished", tail)
        assert [e["data"] for e in tail if e["event"] == "interview.advanced"] == [
            {"question_id": "q1-f", "reason": "silence"}
        ]
        send_v2(ws, "session.end", 3, session_id)
        report = completed(ws)
    first, child = report["interview_items"]
    assert (first["question_id"], first["round"], first["parent_id"]) == ("q1", 1, None)
    assert (child["question_id"], child["round"], child["parent_id"]) == ("q1-f", 2, "q1")
    assert child["transcript"] == ANSWER and child["advance_reason"] == "silence"
    saved = client.app.state.interview_store.get(interview_id)
    assert [i.question.id for i in saved.items] == ["q1", "q1-f"]
    assert client.app.state.model_execution.owner is None


def test_no_follow_ups_ends_the_interview_after_round_one(client, fast) -> None:
    interview_id = make_plan(client)
    session = FakeSession({"follow_up": reply("none", quote="", question="")})
    use_llm(client, session)
    with client.websocket_connect(URL) as ws:
        send_v2(ws, "session.start", 1, data=start_data(interview_id, ["q1"]))
        session_id = until(ws, "session.ready")["session_id"]
        send_v2(ws, "calibration.start", 2, session_id)
        origin = until(ws, "session.running")["data"]["audio_origin_ms"]
        until(ws, "interview.question")
        speak(ws, origin, 1, 0)
        seen: list[dict] = []
        drain_until(ws, "interview.finished", seen)
        stages = [e["data"] for e in seen if e["event"] == "interview.round_break"]
        assert stages == [
            {"stage": "suspending"},
            {"stage": "generating"},
            {"stage": "skipped", "follow_up_count": 0},
        ]
        assert "session.resumed" not in [e["event"] for e in seen]
        ws.send_bytes(  # a client that has not heard yet keeps sending: no error, no incomplete
            struct.pack(">BBIQQI", 2, 2, 3, origin + 1000, 16000, 3200) + LOUD * 3200
        )
        send_v2(ws, "session.end", 3, session_id)
        report = completed(ws)
    assert [i["question_id"] for i in report["interview_items"]] == ["q1"]
    assert report["incomplete"] is False
    assert client.app.state.model_execution.owner is None


def test_an_unanswered_question_skips_the_break_entirely(client, fast) -> None:
    interview_id = make_plan(client)
    llm = use_llm(client, FakeSession({"follow_up": reply("reasoning")}))
    with client.websocket_connect(URL) as ws:
        send_v2(ws, "session.start", 1, data=start_data(interview_id, ["q1"]))
        session_id = until(ws, "session.ready")["session_id"]
        send_v2(ws, "calibration.start", 2, session_id)
        until(ws, "session.running")
        until(ws, "interview.question")
        seen: list[dict] = []
        drain_until(ws, "interview.finished", seen)  # no_response after 4 s
        names = [e["event"] for e in seen]
        assert [e["data"] for e in seen if e["event"] == "interview.round_break"] == [
            {"stage": "skipped", "follow_up_count": 0}
        ]
        assert "session.suspended" not in names and llm.entered == 0
        send_v2(ws, "session.end", 3, session_id)
        completed(ws)


def break_started(ws, client, origin: int, llm: FakeLlm) -> str:
    """Drive round 1 to its end and wait until generation is running inside the model."""
    until(ws, "interview.question")
    speak(ws, origin, 1, 0)
    until(ws, "session.suspended")
    for _ in range(400):
        if llm.session.calls:
            return ""
        time.sleep(0.01)
    raise AssertionError("generation never started")


@pytest.mark.parametrize("how", ["session_end", "disconnect"])
def test_ending_the_session_during_generation_reaps_the_model_and_saves_the_items(
    client, fast, how
) -> None:
    interview_id = make_plan(client)
    llm = use_llm(client, BlockingSession({}))
    execution = client.app.state.model_execution
    with client.websocket_connect(URL) as ws:
        send_v2(ws, "session.start", 1, data=start_data(interview_id, ["q1"]))
        session_id = until(ws, "session.ready")["session_id"]
        send_v2(ws, "calibration.start", 2, session_id)
        origin = until(ws, "session.running")["data"]["audio_origin_ms"]
        break_started(ws, client, origin, llm)
        assert execution.generation_active  # the generation model holds the models
        if how == "session_end":
            send_v2(ws, "session.end", 3, session_id)
            report = completed(ws)
            assert [i["question_id"] for i in report["interview_items"]] == ["q1"]
    assert llm.entered == 1 and llm.exited == 1  # llama-server reaped
    assert execution.owner is None and not execution.generation_active
    saved = client.app.state.interview_store.get(interview_id)
    assert [i.question.id for i in saved.items] == ["q1"] and not saved.running
    assert not client.app.state.live_sessions
    # Nothing is left holding the models: another session can start right away.
    with client.websocket_connect(URL) as ws:
        send_v2(
            ws, "session.start", 1, data={"mode": "interview", "settings": {"gaze_enabled": False}}
        )
        until(ws, "session.ready")


def test_another_session_cannot_start_during_the_break(client, fast) -> None:
    interview_id = make_plan(client)
    llm = use_llm(client, BlockingSession({}))
    with client.websocket_connect(URL) as ws:
        send_v2(ws, "session.start", 1, data=start_data(interview_id, ["q1"]))
        session_id = until(ws, "session.ready")["session_id"]
        send_v2(ws, "calibration.start", 2, session_id)
        origin = until(ws, "session.running")["data"]["audio_origin_ms"]
        break_started(ws, client, origin, llm)
        with client.websocket_connect(URL) as other:
            send_v2(other, "session.start", 1, data={"mode": "interview", "settings": {}})
            error = until(other, "error", allow_error=True)
            assert error["data"]["code"] in {"SESSION_BUSY", "OTHER_SESSION_ACTIVE"}
        send_v2(ws, "session.end", 3, session_id)
        completed(ws)


def test_the_pulse_model_stays_loaded_through_the_break(client, fast) -> None:
    """Pulse keeps being measured during the break (explicit exception to model exclusivity)."""
    interview_id = make_plan(client)
    llm = use_llm(client, BlockingSession({}))
    pulse = client.app.state.pretrained_pulse
    marker = pulse.session = object()  # an ONNX session loaded by round 1
    with client.websocket_connect(URL) as ws:
        send_v2(ws, "session.start", 1, data=start_data(interview_id, ["q1"]))
        session_id = until(ws, "session.ready")["session_id"]
        send_v2(ws, "calibration.start", 2, session_id)
        origin = until(ws, "session.running")["data"]["audio_origin_ms"]
        break_started(ws, client, origin, llm)  # generation is running
        assert pulse.session is marker
        send_v2(ws, "session.end", 3, session_id)
        completed(ws)
