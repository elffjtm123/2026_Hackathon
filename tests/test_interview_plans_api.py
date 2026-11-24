"""Seam: POST /api/v1/interview/plans with a fake InterviewLlm on app.state."""

import asyncio
import json

import pytest
from fastapi.testclient import TestClient

from app.core.errors import AppError
from app.modules.interview.plan import InterviewPlan
from app.modules.interview.questions import PlannedQuestion

URL = "/api/v1/interview/plans"
ORIGIN = {"Origin": "http://testserver"}
NDJSON = {**ORIGIN, "Accept": "application/x-ndjson"}
BODY = {
    "documents": [{"kind": "resume", "text": "이력서 본문입니다."}],
    "job": "AI 엔지니어",
    "exclude_common_ids": ["basic-intro-1"],
}


class FakeInterviewLlm:
    def __init__(self, execution, error: BaseException | None = None) -> None:
        self.execution = execution
        self.error = error
        self.calls: list[tuple] = []
        self.owner_during_call: object = None

    async def plan(self, documents, job, composition, exclude_common_ids, on_progress=None):
        self.calls.append((documents, job, composition, list(exclude_common_ids)))
        self.owner_during_call = self.execution.owner
        if on_progress is not None:
            on_progress({"stage": "loading"})
            on_progress({"stage": "extracting", "completed": 0, "total": 1})
        if self.error is not None:
            raise self.error
        return InterviewPlan(
            questions=[
                PlannedQuestion(
                    id="basic-intro-1",
                    kind="common",
                    subtype="self_introduction",
                    text="자기소개를 해 주세요.",
                    intent="소개",
                ),
                PlannedQuestion(
                    id="doc-1",
                    kind="document",
                    subtype="experience",
                    text="맡은 역할은 무엇인가요?",
                    source_quote="이력서 본문입니다.",
                ),
            ],
            warnings=["few_materials"],
        )


@pytest.fixture
def fake(client: TestClient) -> FakeInterviewLlm:
    llm = FakeInterviewLlm(client.app.state.model_execution)
    client.app.state.interview_llm = llm
    return llm


def code(response) -> str:
    return response.json()["error"]["code"]


def ndjson_lines(response) -> list[dict]:
    return [json.loads(line) for line in response.text.splitlines() if line]


def test_plain_json_returns_id_questions_and_warnings(client, fake) -> None:
    response = client.post(URL, headers=ORIGIN, json=BODY)
    assert response.status_code == 200
    body = response.json()
    assert [q["id"] for q in body["questions"]] == ["basic-intro-1", "doc-1"]
    assert body["questions"][1]["source_quote"] == "이력서 본문입니다."
    assert set(body["questions"][0]) >= {"id", "kind", "subtype", "text", "intent", "round"}
    assert body["warnings"] == ["few_materials"]
    stored = client.app.state.interview_store.get(body["interview_id"])
    assert [q.id for q in stored.plan.questions] == ["basic-intro-1", "doc-1"]
    assert client.app.state.model_execution.owner is None


def test_request_is_forwarded_to_the_generator(client, fake) -> None:
    client.post(URL, headers=ORIGIN, json=BODY)
    documents, job, composition, exclude = fake.calls[0]
    assert [(d.kind.value, d.text) for d in documents] == [("resume", "이력서 본문입니다.")]
    assert job == "AI 엔지니어" and exclude == ["basic-intro-1"]
    assert composition.job == 2
    assert fake.owner_during_call == "interview_plan"


def test_ndjson_streams_progress_then_a_complete_line(client, fake) -> None:
    response = client.post(URL, headers=NDJSON, json=BODY)
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/x-ndjson")
    lines = ndjson_lines(response)
    assert [line["event"] for line in lines] == ["progress", "progress", "complete"]
    assert lines[0]["data"] == {"stage": "loading"}
    final = lines[-1]["data"]
    assert [q["id"] for q in final["questions"]] == ["basic-intro-1", "doc-1"]
    assert client.app.state.interview_store.get(final["interview_id"])
    assert client.app.state.model_execution.owner is None


def test_documents_may_be_empty_for_common_only_plans(client, fake) -> None:
    response = client.post(URL, headers=ORIGIN, json={**BODY, "documents": []})
    assert response.status_code == 200
    assert fake.calls[0][0] == []


@pytest.mark.parametrize(
    "mutate",
    [
        lambda b: b.update(job="가" * 31),
        lambda b: b.update(documents=[{"kind": "resume", "text": "a"}] * 2),
        lambda b: b.update(documents=[{"kind": "diary", "text": "a"}]),
        lambda b: b.update(
            documents=[{"kind": k, "text": "a"} for k in ("resume", "cover_letter", "portfolio")]
            + [{"kind": "resume", "text": "a"}]
        ),
        lambda b: b.update(documents=[{"kind": "resume", "text": "가" * 30_001}]),
        lambda b: b.update(
            documents=[
                {"kind": "resume", "text": "가" * 20_000},
                {"kind": "portfolio", "text": "나" * 10_001},
            ]
        ),
        lambda b: b.update(exclude_common_ids=["x"] * 200),
    ],
    ids=["long-job", "dup-kind", "bad-kind", "four-docs", "long-text", "total", "ids"],
)
def test_invalid_bodies_are_422_without_echoing_text(client, fake, mutate) -> None:
    body = json.loads(json.dumps(BODY))
    mutate(body)
    response = client.post(URL, headers=ORIGIN, json=body)
    assert response.status_code == 422
    assert "가가가가" not in response.text
    assert fake.calls == []
    assert client.app.state.model_execution.owner is None


@pytest.mark.parametrize("job", [None, "", "   "])
def test_job_is_optional(client, fake, job) -> None:
    body = {k: v for k, v in BODY.items() if k != "job"}
    if job is not None:
        body["job"] = job
    assert client.post(URL, headers=ORIGIN, json=body).status_code == 200
    assert fake.calls[0][1] is None


def test_job_is_stripped(client, fake) -> None:
    client.post(URL, headers=ORIGIN, json={**BODY, "job": "  백엔드  "})
    assert fake.calls[0][1] == "백엔드"


async def test_ndjson_ends_with_an_error_line_when_storing_the_plan_fails(client, fake) -> None:
    def boom(plan):
        raise RuntimeError("store down")

    client.app.state.interview_store.create = boom
    messages: asyncio.Queue = asyncio.Queue()
    await messages.put({"type": "http.request", "body": json.dumps(BODY).encode()})
    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "POST",
        "scheme": "http",
        "path": URL,
        "raw_path": URL.encode(),
        "query_string": b"",
        "headers": [
            (b"content-type", b"application/json"),
            (b"origin", b"http://testserver"),
            (b"accept", b"application/x-ndjson"),
        ],
        "client": ("127.0.0.1", 50000),
        "server": ("testserver", 80),
    }
    sent: list[dict] = []

    async def send(message):
        sent.append(message)

    task = asyncio.create_task(client.app(scope, messages.get, send))
    try:
        # A stream without a terminal line would hang here; fail fast instead.
        await asyncio.wait_for(task, timeout=3)
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
    body = b"".join(m.get("body", b"") for m in sent if m["type"] == "http.response.body")
    last = json.loads(body.decode().splitlines()[-1])
    assert last["event"] == "error" and last["data"]["code"] == "INTERVIEW_PLAN_FAILED"
    assert client.app.state.model_execution.owner is None


def test_requires_local_ai_mode(client, fake) -> None:
    client.app.state.settings.ai_mode = "http"
    response = client.post(URL, headers=ORIGIN, json=BODY)
    assert (response.status_code, code(response)) == (409, "LOCAL_MODE_REQUIRED")


def test_requires_allowed_origin(client, fake) -> None:
    for headers in ({}, {"Origin": "https://evil.example"}):
        response = client.post(URL, headers=headers, json=BODY)
        assert (response.status_code, code(response)) == (403, "DEVELOPMENT_ONLY")
    assert fake.calls == []


def test_blocked_while_practicing(client, fake) -> None:
    client.app.state.live_sessions.add("test-session")
    response = client.post(URL, headers=ORIGIN, json=BODY)
    assert (response.status_code, code(response)) == (409, "PRACTICE_ACTIVE")


@pytest.mark.parametrize(
    ("owner", "expected"),
    [
        ("summary", "SUMMARY_BUSY"),
        ("interview_plan", "INTERVIEW_BUSY"),
        ("interview_evaluation", "INTERVIEW_BUSY"),
    ],
)
def test_blocked_while_an_offline_job_owns_the_models(client, fake, owner, expected) -> None:
    client.app.state.model_execution.owner = owner
    response = client.post(URL, headers=ORIGIN, json=BODY)
    assert (response.status_code, code(response)) == (409, expected)
    assert fake.calls == []
    assert client.app.state.model_execution.owner == owner  # someone else's reservation stays


def test_blocked_while_a_session_owns_the_models(client, fake) -> None:
    from uuid import uuid4

    client.app.state.model_execution.owner = uuid4()
    response = client.post(URL, headers=ORIGIN, json=BODY)
    assert (response.status_code, code(response)) == (409, "PRACTICE_ACTIVE")


@pytest.mark.parametrize(
    ("raised", "status", "expected"),
    [
        (AppError("INTERVIEW_MODEL_UNAVAILABLE", "준비", 503), 503, "INTERVIEW_MODEL_UNAVAILABLE"),
        (AppError("INTERVIEW_PLAN_FAILED", "실패", 504), 504, "INTERVIEW_PLAN_FAILED"),
        (RuntimeError("boom"), 503, "INTERVIEW_PLAN_FAILED"),
    ],
)
def test_errors_release_the_reservation(client, fake, raised, status, expected) -> None:
    fake.error = raised
    response = client.post(URL, headers=ORIGIN, json=BODY)
    assert response.status_code == status
    assert client.app.state.model_execution.owner is None
    assert len(client.app.state.interview_store) == 0


def test_ndjson_errors_become_an_error_line_and_release(client, fake) -> None:
    fake.error = AppError("INTERVIEW_MODEL_UNAVAILABLE", "준비해 주세요.", 503)
    lines = ndjson_lines(client.post(URL, headers=NDJSON, json=BODY))
    assert lines[-1] == {
        "event": "error",
        "data": {"code": "INTERVIEW_MODEL_UNAVAILABLE", "message": "준비해 주세요."},
    }
    fake.error = RuntimeError("boom")
    lines = ndjson_lines(client.post(URL, headers=NDJSON, json=BODY))
    assert lines[-1]["data"]["code"] == "INTERVIEW_PLAN_FAILED"
    assert client.app.state.model_execution.owner is None


def test_guard_errors_are_plain_http_errors_even_for_ndjson(client, fake) -> None:
    client.app.state.model_execution.owner = "summary"
    response = client.post(URL, headers=NDJSON, json=BODY)
    assert (response.status_code, code(response)) == (409, "SUMMARY_BUSY")


class BlockingLlm:
    """plan() waits forever; records that its cleanup ran while the model was still reserved."""

    def __init__(self, execution) -> None:
        self.execution = execution
        self.started = asyncio.Event()
        self.owner_at_cleanup: object = "unset"

    async def plan(self, *args, **kwargs):
        self.started.set()
        try:
            await asyncio.Event().wait()
        finally:
            await asyncio.sleep(0.05)  # stands in for reaping llama-server
            self.owner_at_cleanup = self.execution.owner


@pytest.mark.parametrize("stream", [False, True])
async def test_disconnect_reaps_before_releasing_the_reservation(client, stream) -> None:
    execution = client.app.state.model_execution
    llm = BlockingLlm(execution)
    client.app.state.interview_llm = llm
    messages: asyncio.Queue = asyncio.Queue()
    await messages.put({"type": "http.request", "body": json.dumps(BODY).encode()})
    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "POST",
        "scheme": "http",
        "path": URL,
        "raw_path": URL.encode(),
        "query_string": b"",
        "headers": [
            (b"content-type", b"application/json"),
            (b"origin", b"http://testserver"),
            (b"accept", b"application/x-ndjson" if stream else b"application/json"),
        ],
        "client": ("127.0.0.1", 50000),
        "server": ("testserver", 80),
    }
    sent: list[dict] = []

    async def send(message):
        sent.append(message)

    task = asyncio.create_task(client.app(scope, messages.get, send))
    try:
        await asyncio.wait_for(llm.started.wait(), timeout=2)
        assert execution.owner == "interview_plan"
        await messages.put({"type": "http.disconnect"})
        for _ in range(200):
            if execution.owner is None:
                break
            await asyncio.sleep(0.01)
        assert execution.owner is None
        assert llm.owner_at_cleanup == "interview_plan"
        await asyncio.wait_for(task, timeout=2)
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
    assert len(client.app.state.interview_store) == 0
