"""Seam: /api/v1/interview/{id}/evaluation with a fake InterviewLlm and LocalLlm on app.state."""

import asyncio
import json
from contextlib import asynccontextmanager
from uuid import uuid4

import pytest

from app.core.errors import AppError
from app.modules.interview.evaluation import (
    EvaluationSummary,
    Grade,
    InterviewEvaluation,
    ItemEvaluation,
)
from app.modules.interview.plan import InterviewPlan
from app.modules.interview.questions import ItemRecord, PlannedQuestion, RubricItem
from app.services.interview_store import InterviewStore

ORIGIN = {"Origin": "http://testserver"}
NDJSON = {**ORIGIN, "Accept": "application/x-ndjson"}


def url(interview_id: str) -> str:
    return f"/api/v1/interview/{interview_id}/evaluation"


def canned() -> InterviewEvaluation:
    grade = Grade(3, "검출 모델을 학습시키고", "main", "근거가 있다.", "수치를 더하세요.")
    return InterviewEvaluation(
        items=[
            ItemEvaluation(
                "q1",
                "evaluated",
                grades={RubricItem.REASONING: grade},
                excluded_items=[RubricItem.SPECIFICITY],
                partial=True,
                score=15.0,
                follow_up_ids=["fu-1"],
            ),
            ItemEvaluation("q2", "not_evaluable", not_evaluable_reason="too_short"),
        ],
        overall_score=15.0,
        summary=EvaluationSummary(["잘한 점"], ["고칠 점"], ["목표"]),
        model="m.gguf",
        elapsed_seconds=1.5,
        warnings=["summary_failed"],
    )


class FakeLocalLlm:
    def __init__(self, execution, error: BaseException | None = None) -> None:
        self.execution = execution
        self.error = error
        self.entered = self.exited = 0
        self.owner_at_exit: object = "unset"

    @asynccontextmanager
    async def loaded(self):
        if self.error is not None:
            raise self.error
        self.entered += 1
        try:
            yield "session"
        finally:
            await asyncio.sleep(0.02)  # stands in for reaping llama-server
            self.exited += 1
            self.owner_at_exit = self.execution.owner


class FakeInterviewLlm:
    def __init__(self, execution, error: BaseException | None = None) -> None:
        self.execution = execution
        self.error = error
        self.calls: list[tuple] = []
        self.owner_during_call: object = None
        self.started = asyncio.Event()
        self.block = False

    async def evaluate(self, items, session, on_progress=None):
        self.calls.append((list(items), session))
        self.owner_during_call = self.execution.owner
        if on_progress is not None:
            on_progress({"stage": "evaluating", "index": 1, "total": 2})
            on_progress({"stage": "summarizing"})
        self.started.set()
        if self.block:
            await asyncio.Event().wait()
        if self.error is not None:
            raise self.error
        return canned()


@pytest.fixture
def fake(client):
    execution = client.app.state.model_execution
    llm = FakeInterviewLlm(execution)
    client.app.state.interview_llm = llm
    client.app.state.local_llm = FakeLocalLlm(execution)
    return llm


def finished_interview(client, store=None) -> str:
    store = store or client.app.state.interview_store
    plan = InterviewPlan(
        questions=[PlannedQuestion(id="q1", kind="common", subtype="x", text="질문")]
    )
    interview_id = store.create(plan)
    store.attach_session(interview_id, uuid4(), ["q1"])
    store.save_items(
        interview_id, [ItemRecord(plan.questions[0], 0, None, 10, "stopped", False, [], "")]
    )
    return interview_id


def code(response) -> str:
    return response.json()["error"]["code"]


def ndjson_lines(response) -> list[dict]:
    return [json.loads(line) for line in response.text.splitlines() if line]


def test_ndjson_streams_progress_then_the_evaluation(client, fake) -> None:
    interview_id = finished_interview(client)
    response = client.get(url(interview_id), headers=NDJSON)
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/x-ndjson")
    lines = ndjson_lines(response)
    assert [line["event"] for line in lines] == [
        "progress",
        "progress",
        "progress",
        "progress",
        "complete",
    ]
    assert [line["data"]["stage"] for line in lines[:-1]] == [
        "loading",
        "evaluating",
        "summarizing",
        "cleaning",
    ]
    final = lines[-1]["data"]
    assert final["overall_score"] == 15.0 and final["model"] == "m.gguf"
    first = final["items"][0]
    assert first["status"] == "evaluated" and first["partial"] is True
    assert first["excluded_items"] == ["specificity"] and first["follow_up_ids"] == ["fu-1"]
    assert first["grades"]["reasoning"] == {
        "grade": 3,
        "evidence_quote": "검출 모델을 학습시키고",
        "evidence_source": "main",
        "reason": "근거가 있다.",
        "improvement": "수치를 더하세요.",
    }
    assert final["items"][1]["not_evaluable_reason"] == "too_short"
    assert final["summary"] == {
        "strengths": ["잘한 점"],
        "improvements": ["고칠 점"],
        "next_goals": ["목표"],
    }
    assert final["warnings"] == ["summary_failed"]
    assert client.app.state.model_execution.owner is None


def test_the_model_is_loaded_once_and_the_stored_items_are_evaluated(client, fake) -> None:
    interview_id = finished_interview(client)
    client.get(url(interview_id), headers=ORIGIN)
    state = client.app.state
    assert state.local_llm.entered == state.local_llm.exited == 1
    items, session = fake.calls[0]
    assert session == "session" and [i.question.id for i in items] == ["q1"]
    assert fake.owner_during_call == "interview_evaluation"
    assert state.local_llm.owner_at_exit == "interview_evaluation"  # released after cleanup
    assert state.interview_store.get(interview_id).evaluation is not None
    assert not state.interview_store.get(interview_id).evaluating


def test_plain_json_returns_the_evaluation(client, fake) -> None:
    interview_id = finished_interview(client)
    response = client.get(url(interview_id), headers=ORIGIN)
    assert response.status_code == 200
    assert response.json()["overall_score"] == 15.0
    assert client.app.state.model_execution.owner is None


def test_an_unknown_interview_is_not_found(client, fake) -> None:
    response = client.get(url("missing"), headers=ORIGIN)
    assert (response.status_code, code(response)) == (404, "INTERVIEW_NOT_FOUND")


def test_an_interview_that_has_not_ended_is_not_ready(client, fake) -> None:
    store = client.app.state.interview_store
    plan = InterviewPlan(questions=[PlannedQuestion(id="q1", kind="common", subtype="x", text="q")])
    never_started = store.create(plan)
    running = store.create(plan)
    store.attach_session(running, uuid4(), ["q1"])
    for interview_id in (never_started, running):
        response = client.get(url(interview_id), headers=ORIGIN)
        assert (response.status_code, code(response)) == (409, "INTERVIEW_NOT_READY")
        assert "면접이 끝난 뒤" in response.json()["error"]["message"]
    assert fake.calls == [] and client.app.state.model_execution.owner is None


def test_a_second_request_replays_the_stored_result_without_the_model(client, fake) -> None:
    interview_id = finished_interview(client)
    first = client.get(url(interview_id), headers=NDJSON)
    again = client.get(url(interview_id), headers=NDJSON)
    lines = ndjson_lines(again)
    assert [line["event"] for line in lines] == ["complete"]
    assert lines[0]["data"] == ndjson_lines(first)[-1]["data"]
    assert len(fake.calls) == 1 and client.app.state.local_llm.entered == 1
    assert client.get(url(interview_id), headers=ORIGIN).json() == lines[0]["data"]


def test_a_delivered_result_is_removed_thirty_minutes_later(client, fake) -> None:
    now = [1000.0]
    store = InterviewStore(7200, 50, clock=lambda: now[0])
    client.app.state.interview_store = store
    interview_id = finished_interview(client, store)
    client.get(url(interview_id), headers=NDJSON)
    now[0] += 1799
    assert client.get(url(interview_id), headers=ORIGIN).status_code == 200  # replay
    now[0] += 2
    response = client.get(url(interview_id), headers=ORIGIN)
    assert (response.status_code, code(response)) == (404, "INTERVIEW_NOT_FOUND")
    assert len(fake.calls) == 1


def test_an_evaluation_that_is_already_running_is_busy(client, fake) -> None:
    interview_id = finished_interview(client)
    client.app.state.interview_store.begin_evaluation(interview_id)
    response = client.get(url(interview_id), headers=ORIGIN)
    assert (response.status_code, code(response)) == (409, "INTERVIEW_BUSY")
    assert fake.calls == []


def test_requires_local_ai_mode_and_an_allowed_origin(client, fake) -> None:
    interview_id = finished_interview(client)
    for headers in ({}, {"Origin": "https://evil.example"}):
        response = client.get(url(interview_id), headers=headers)
        assert (response.status_code, code(response)) == (403, "DEVELOPMENT_ONLY")
    client.app.state.settings.ai_mode = "http"
    response = client.get(url(interview_id), headers=ORIGIN)
    assert (response.status_code, code(response)) == (409, "LOCAL_MODE_REQUIRED")
    assert fake.calls == []


def test_blocked_while_practicing(client, fake) -> None:
    interview_id = finished_interview(client)
    client.app.state.live_sessions.add("test-session")
    response = client.get(url(interview_id), headers=ORIGIN)
    assert (response.status_code, code(response)) == (409, "PRACTICE_ACTIVE")
    assert fake.calls == []


@pytest.mark.parametrize(
    ("owner", "expected"),
    [("summary", "SUMMARY_BUSY"), ("interview_plan", "INTERVIEW_BUSY")],
)
def test_blocked_while_another_offline_job_owns_the_models(client, fake, owner, expected) -> None:
    interview_id = finished_interview(client)
    client.app.state.model_execution.owner = owner
    response = client.get(url(interview_id), headers=NDJSON)
    assert (response.status_code, code(response)) == (409, expected)
    assert client.app.state.model_execution.owner == owner  # not released by this request
    assert fake.calls == []


@pytest.mark.parametrize(
    ("raised", "status", "expected"),
    [
        (AppError("LOCAL_MODEL_UNAVAILABLE", "준비", 503), 503, "INTERVIEW_MODEL_UNAVAILABLE"),
        (asyncio.TimeoutError(), 504, "INTERVIEW_EVALUATION_FAILED"),
        (ValueError("failed to start"), 503, "INTERVIEW_EVALUATION_FAILED"),
    ],
)
def test_model_start_failures_map_to_codes_and_release(
    client, fake, raised, status, expected
) -> None:
    client.app.state.local_llm.error = raised
    interview_id = finished_interview(client)
    response = client.get(url(interview_id), headers=ORIGIN)
    assert (response.status_code, code(response)) == (status, expected)
    lines = ndjson_lines(client.get(url(interview_id), headers=NDJSON))
    assert lines[-1]["event"] == "error" and lines[-1]["data"]["code"] == expected
    assert client.app.state.model_execution.owner is None
    state = client.app.state.interview_store.get(interview_id)
    assert state.evaluation is None and not state.evaluating  # a retry is possible


def test_an_unexpected_error_in_evaluate_is_a_503_and_releases(client, fake) -> None:
    fake.error = RuntimeError("boom with a transcript 가나다")
    interview_id = finished_interview(client)
    response = client.get(url(interview_id), headers=ORIGIN)
    assert (response.status_code, code(response)) == (503, "INTERVIEW_EVALUATION_FAILED")
    assert "가나다" not in response.text
    assert client.app.state.model_execution.owner is None
    assert client.app.state.local_llm.exited == 1


def test_delete_without_a_running_evaluation_is_204_and_unknown_is_404(client, fake) -> None:
    interview_id = finished_interview(client)
    assert client.delete(url(interview_id), headers=ORIGIN).status_code == 204
    response = client.delete(url("missing"), headers=ORIGIN)
    assert (response.status_code, code(response)) == (404, "INTERVIEW_NOT_FOUND")
    assert client.delete(url(interview_id)).status_code == 403  # no Origin


# --- cancellation: driven through the ASGI app on the test's own loop -------------------


def start_request(app, method: str, path: str, accept: bytes):
    messages: asyncio.Queue = asyncio.Queue()
    messages.put_nowait({"type": "http.request", "body": b""})
    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": method,
        "scheme": "http",
        "path": path,
        "raw_path": path.encode(),
        "query_string": b"",
        "headers": [(b"origin", b"http://testserver"), (b"accept", accept)],
        "client": ("127.0.0.1", 50000),
        "server": ("testserver", 80),
    }
    sent: list[dict] = []

    async def send(message):
        sent.append(message)

    return asyncio.create_task(app(scope, messages.get, send)), messages, sent


def body_of(sent: list[dict]) -> str:
    return b"".join(m.get("body", b"") for m in sent if m["type"] == "http.response.body").decode()


def status_of(sent: list[dict]) -> int:
    return next(m["status"] for m in sent if m["type"] == "http.response.start")


async def wait_until(condition) -> None:
    for _ in range(300):
        if condition():
            return
        await asyncio.sleep(0.01)
    raise AssertionError("condition not reached")


@pytest.mark.parametrize("accept", [b"application/x-ndjson", b"application/json"])
async def test_disconnect_reaps_before_releasing_the_reservation(client, fake, accept) -> None:
    state = client.app.state
    fake.block = True
    interview_id = finished_interview(client)
    task, messages, _ = start_request(client.app, "GET", url(interview_id), accept)
    try:
        await asyncio.wait_for(fake.started.wait(), timeout=2)
        assert state.model_execution.owner == "interview_evaluation"
        await messages.put({"type": "http.disconnect"})
        await wait_until(lambda: state.model_execution.owner is None)
        assert state.local_llm.exited == 1
        assert state.local_llm.owner_at_exit == "interview_evaluation"
        await asyncio.wait_for(task, timeout=2)
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
    stored = state.interview_store.get(interview_id)
    assert stored.evaluation is None and not stored.evaluating


@pytest.mark.parametrize("accept", [b"application/x-ndjson", b"application/json"])
async def test_delete_cancels_a_running_evaluation_and_waits_for_cleanup(
    client, fake, accept
) -> None:
    state = client.app.state
    fake.block = True
    interview_id = finished_interview(client)
    run, _, sent = start_request(client.app, "GET", url(interview_id), accept)
    try:
        await asyncio.wait_for(fake.started.wait(), timeout=2)
        cancel, _, cancel_sent = start_request(client.app, "DELETE", url(interview_id), b"*/*")
        await asyncio.wait_for(cancel, timeout=3)
        assert status_of(cancel_sent) == 204
        # Right when DELETE answers, llama-server is gone and the reservation is free.
        assert state.local_llm.exited == 1 and state.model_execution.owner is None
        await asyncio.wait_for(run, timeout=3)
    finally:
        run.cancel()
        await asyncio.gather(run, return_exceptions=True)
    if accept == b"application/x-ndjson":
        last = json.loads(body_of(sent).splitlines()[-1])
        assert last["event"] == "error"
        assert last["data"]["code"] == "INTERVIEW_EVALUATION_CANCELLED"
    else:
        assert status_of(sent) == 499
    stored = state.interview_store.get(interview_id)
    assert stored.evaluation is None and not stored.evaluating
    # The reservation is free again, so a new evaluation can run.
    fake.block = False
    assert client.get(url(interview_id), headers=ORIGIN).status_code == 200


class CancelOnRegister(dict):
    """Cancels a task the moment it is registered, before it ever takes a step (a DELETE that
    lands between the start of the evaluation and the first step of its task)."""

    def __setitem__(self, key, task) -> None:
        super().__setitem__(key, task)
        task.cancel()


async def test_delete_before_the_first_step_still_ends_the_stream(client, fake) -> None:
    state = client.app.state
    state.interview_evaluations = CancelOnRegister()
    interview_id = finished_interview(client)
    run, _, sent = start_request(client.app, "GET", url(interview_id), b"application/x-ndjson")
    try:
        await asyncio.wait_for(run, timeout=3)  # a stream without a terminal line hangs here
    finally:
        run.cancel()
        await asyncio.gather(run, return_exceptions=True)
    lines = body_of(sent).splitlines()
    last = json.loads(lines[-1])
    assert last["event"] == "error"
    assert last["data"]["code"] == "INTERVIEW_EVALUATION_CANCELLED"
    assert [json.loads(line)["event"] for line in lines].count("error") == 1
    assert fake.calls == [] and state.model_execution.owner is None
    assert not state.interview_store.get(interview_id).evaluating


def test_a_completed_session_no_longer_blocks_the_evaluation_request(
    client, fake, monkeypatch
) -> None:
    """The client may call the API the moment it receives session.completed, while the socket
    handler is still finishing (its cleanup removes the session from `live_sessions` later)."""
    from app.realtime.pipeline import SessionPipeline
    from tests.test_session_flow import send_v2

    stop = SessionPipeline.stop

    async def slow_cleanup(self, *args, **kwargs):
        result = await stop(self, *args, **kwargs)
        await asyncio.sleep(0.5)  # the handler's finally runs this long after session.completed
        return result

    monkeypatch.setattr(SessionPipeline, "stop", slow_cleanup)
    with client.websocket_connect("/api/v1/ws/practice-demo?protocol=2") as ws:
        send_v2(ws, "session.start", 1, data={"settings": {"gaze_enabled": False}})
        ready = ws.receive_json()
        assert client.get(url("missing"), headers=ORIGIN).status_code == 409  # still practicing
        send_v2(ws, "session.end", 2, ready["session_id"])
        while ws.receive_json()["event"] != "session.completed":
            pass
        response = client.get(url("missing"), headers=ORIGIN)
        assert (response.status_code, code(response)) == (404, "INTERVIEW_NOT_FOUND")
