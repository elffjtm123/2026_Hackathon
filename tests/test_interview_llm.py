"""Seam: InterviewLlm.plan with a fake LocalLlm session returning canned JSON."""

import asyncio
import json
import random
import time
from contextlib import asynccontextmanager

import pytest

from app.ai.interview_llm import InterviewLlm
from app.core.errors import AppError
from app.modules.interview.composition import Composition
from app.modules.interview.documents import DocumentKind, DocumentText

PROJECT = "소형 객체 검출 데이터 증강 연구에서 모델 학습 파이프라인을 설계했습니다."
SKILL = "PyTorch, ONNX, FastAPI를 사용해 추론 서버를 만들었습니다."
ACTIVITY = "교내 AI 동아리에서 스터디 운영진으로 활동했습니다."
DOCUMENT = f"프로젝트\n{PROJECT}\n\n기술\n{SKILL}\n활동\n{ACTIVITY}\n"


def doc(text: str = DOCUMENT, kind: DocumentKind = DocumentKind.RESUME) -> DocumentText:
    return DocumentText(kind=kind, text=text)


MATERIALS = {
    "items": [
        {"kind": "project", "quote": PROJECT, "summary": "소형 객체 검출 연구"},
        {"kind": "skill", "quote": SKILL, "summary": "추론 서버 구현"},
        {"kind": "activity", "quote": ACTIVITY, "summary": "동아리 스터디 운영"},
    ]
}


def question(subtype: str, index: int, text: str) -> dict:
    return {"subtype": subtype, "material_index": index, "text": text, "intent": "확인"}


QUESTIONS = {
    "questions": [
        question("job", 1, "추론 서버를 만들 때 FastAPI를 선택한 이유는 무엇인가요?"),
        question("job", 0, "객체 검출 연구의 데이터 증강 기법을 직무에 어떻게 적용하시겠습니까?"),
        question("experience", 0, "객체 검출 연구에서 본인이 맡은 역할과 직접 한 일은 무엇인가요?"),
        question("experience", 2, "동아리 스터디를 운영하며 새로 배운 점은 무엇이었나요?"),
    ]
}


class FakeSession:
    """Replies per schema name; a reply is a JSON value, an exception, or a list of those."""

    def __init__(self, replies: dict[str, object]) -> None:
        self.replies = {k: (list(v) if isinstance(v, list) else [v]) for k, v in replies.items()}
        self.calls: list[tuple[str, str]] = []  # (schema_name, prompt)
        self.seeds: list[int] = []
        self.on_call = None  # optional hook run at the start of every call

    async def count_tokens(self, prompt: str) -> int:
        return len(prompt) // 3

    async def complete_json(
        self, prompt, schema, *, max_tokens, on_delta=None, schema_name="x", seed=42
    ):
        self.calls.append((schema_name, prompt))
        self.seeds.append(seed)
        if self.on_call is not None:
            self.on_call()
        queue = self.replies[schema_name]
        reply = queue.pop(0) if len(queue) > 1 else queue[0]
        if isinstance(reply, BaseException):
            raise reply
        return reply

    def count(self, name: str) -> int:
        return sum(1 for n, _ in self.calls if n == name)


class FakeLlm:
    def __init__(self, session: FakeSession | None = None, error: Exception | None = None):
        self.session, self.error = session, error
        self.entered = self.exited = 0

    @asynccontextmanager
    async def loaded(self):
        if self.error is not None:
            raise self.error
        self.entered += 1
        try:
            yield self.session
        finally:
            self.exited += 1


def happy_session() -> FakeSession:
    return FakeSession({"materials": MATERIALS, "questions": QUESTIONS})


def make(session: FakeSession | None = None, **kwargs) -> tuple[InterviewLlm, FakeLlm]:
    llm = FakeLlm(session or happy_session(), kwargs.pop("error", None))
    return InterviewLlm(llm, rng=random.Random(1), **kwargs), llm


async def plan(
    interview: InterviewLlm, documents=None, exclude=(), progress=None, job="AI 엔지니어"
):
    return await interview.plan(
        [doc()] if documents is None else documents,
        job,
        Composition(),
        exclude,
        progress,
    )


def kinds(result) -> list[str]:
    return [q.kind for q in result.questions]


async def test_happy_path_builds_the_default_eight_questions_in_order() -> None:
    interview, llm = make()
    result = await plan(interview)
    assert len(result.questions) == 9
    assert sorted(kinds(result)) == ["common"] * 5 + ["document"] * 4
    assert result.warnings == []
    subtypes = [q.subtype for q in result.questions]
    assert subtypes[0] == "self_introduction"
    assert subtypes[-1] == "closing"
    doc_questions = [q for q in result.questions if q.kind == "document"]
    assert {q.subtype for q in doc_questions} == {"job", "experience"}
    assert all(q.source_quote and q.rubric_items for q in doc_questions)
    assert llm.entered == llm.exited == 1  # one model load for both calls
    assert llm.session.count("materials") == 1 and llm.session.count("questions") == 1


async def test_questions_follow_the_composition_order() -> None:
    interview, _ = make()
    result = await plan(interview)
    order = Composition().order_questions(list(result.questions))
    assert [q.id for q in order] == [q.id for q in result.questions]


async def test_quote_missing_from_the_document_is_dropped() -> None:
    materials = {
        "items": [
            *MATERIALS["items"][:2],
            {"kind": "activity", "quote": "문서에 없는 문장입니다.", "summary": "x"},
        ]
    }
    session = FakeSession({"materials": materials, "questions": QUESTIONS})
    interview, _ = make(session)
    result = await plan(interview)
    quotes = [q.source_quote for q in result.questions if q.kind == "document"]
    assert "문서에 없는 문장입니다." not in quotes
    # The question prompt only offers the two valid materials, so index 2 is out of range.
    assert len(quotes) == 3
    assert "few_materials" in result.warnings
    assert sum(1 for q in result.questions if q.kind == "common") == 6


async def test_quote_matches_after_whitespace_normalization() -> None:
    spaced = PROJECT.replace(" ", "  \n ")
    session = FakeSession(
        {
            "materials": {"items": [{"kind": "project", "quote": spaced, "summary": "s"}]},
            "questions": {"questions": [question("experience", 0, "맡은 역할은 무엇인가요?")]},
        }
    )
    interview, _ = make(session)
    result = await plan(interview)
    assert [q.source_quote for q in result.questions if q.kind == "document"] == [PROJECT]


async def test_banned_topic_question_is_dropped() -> None:
    bad = {
        "questions": [
            *QUESTIONS["questions"][:3],
            question("experience", 2, "가족 중에 동아리를 권유한 분이 있나요?"),
        ]
    }
    interview, _ = make(FakeSession({"materials": MATERIALS, "questions": bad}))
    result = await plan(interview)
    assert all("가족" not in q.text for q in result.questions)
    assert len([q for q in result.questions if q.kind == "document"]) == 3
    assert len(result.questions) == 9  # filled with a common question


async def test_invalid_questions_are_dropped_not_fatal() -> None:
    mixed = {
        "questions": [
            question("job", 1, "A는 무엇인가요? B는 무엇인가요?"),  # double question
            question("job", 9, "범위를 벗어난 근거 번호입니다."),
            question("experience", 2, "x" * 101),  # too long
            *QUESTIONS["questions"],
        ]
    }
    interview, _ = make(FakeSession({"materials": MATERIALS, "questions": mixed}))
    result = await plan(interview)
    assert len([q for q in result.questions if q.kind == "document"]) == 4


async def test_material_kind_must_fit_the_question_subtype() -> None:
    wrong = {
        "questions": [
            question("job", 2, "동아리 활동을 직무에 어떻게 쓰나요?"),
            *QUESTIONS["questions"],
        ]
    }
    interview, _ = make(FakeSession({"materials": MATERIALS, "questions": wrong}))
    result = await plan(interview)
    assert all("동아리 활동을 직무" not in q.text for q in result.questions)


async def test_failed_call_is_retried_once_then_succeeds() -> None:
    session = FakeSession({"materials": [ValueError("bad"), MATERIALS], "questions": QUESTIONS})
    interview, _ = make(session)
    result = await plan(interview)
    assert session.count("materials") == 2
    assert result.warnings == [] and len(result.questions) == 9


async def test_malformed_response_is_retried_once() -> None:
    session = FakeSession({"materials": [{"nope": 1}, MATERIALS], "questions": QUESTIONS})
    interview, _ = make(session)
    await plan(interview)
    assert session.count("materials") == 2


async def test_hallucinated_materials_only_counts_as_validation_failure_and_retries() -> None:
    fake = {"items": [{"kind": "project", "quote": "없는 문장", "summary": "x"}]}
    session = FakeSession({"materials": [fake, MATERIALS], "questions": QUESTIONS})
    interview, _ = make(session)
    result = await plan(interview)
    assert session.count("materials") == 2 and result.warnings == []


async def test_two_failures_fall_back_to_common_questions_with_a_warning() -> None:
    session = FakeSession({"materials": ValueError("bad"), "questions": QUESTIONS})
    interview, llm = make(session)
    result = await plan(interview)
    assert session.count("materials") == 2  # initial call plus one retry, no more
    assert session.count("questions") == 0
    assert result.warnings == ["document_questions_failed"]
    assert kinds(result) == ["common"] * len(result.questions)
    assert len(result.questions) == 9
    assert llm.entered == llm.exited == 1


async def test_question_call_failing_twice_also_falls_back() -> None:
    session = FakeSession({"materials": MATERIALS, "questions": ValueError("bad")})
    interview, _ = make(session)
    result = await plan(interview)
    assert session.count("questions") == 2
    assert result.warnings == ["document_questions_failed"]


async def test_short_document_questions_are_filled_with_common_ones() -> None:
    one = {"questions": QUESTIONS["questions"][:1]}
    interview, _ = make(FakeSession({"materials": MATERIALS, "questions": one}))
    result = await plan(interview)
    assert len(result.questions) == 9
    assert kinds(result).count("document") == 1
    assert result.warnings == ["few_materials"]
    ids = [q.id for q in result.questions]
    assert len(set(ids)) == len(ids)


@pytest.mark.parametrize(
    "documents",
    [
        [],
        [doc("")],
        [doc("   \n ")],
        [doc("", DocumentKind.RESUME), doc("", DocumentKind.PORTFOLIO)],
    ],
)
async def test_empty_documents_skip_the_llm(documents) -> None:
    interview, llm = make()
    result = await plan(interview, documents)
    assert llm.entered == 0
    assert kinds(result) == ["common"] * 9
    assert result.warnings == ["few_materials"]


async def test_result_holds_no_document_text() -> None:
    interview, _ = make()
    result = await plan(interview)
    blob = json.dumps([vars(q) for q in result.questions], ensure_ascii=False, default=str)
    assert DOCUMENT not in blob and "프로젝트\n" not in blob
    for q in result.questions:
        if q.kind == "document":
            assert q.source_quote in {PROJECT, SKILL, ACTIVITY}
    assert not hasattr(result, "materials")


async def test_progress_stages_are_reported_in_order() -> None:
    interview, _ = make()
    stages: list[str] = []
    await plan(interview, progress=lambda data: stages.append(data["stage"]))
    order = ["loading", "extracting", "generating", "validating", "cleaning", "done"]
    assert [s for s in order if s in stages] == order
    assert stages == sorted(stages, key=order.index)


async def test_progress_observer_errors_do_not_break_planning() -> None:
    def broken(data):
        raise RuntimeError("observer")

    interview, llm = make()
    result = await plan(interview, progress=broken)
    assert len(result.questions) == 9 and llm.exited == 1


async def test_excluded_common_ids_are_not_picked() -> None:
    interview, _ = make()
    first = await plan(interview, [])
    exclude = [q.bank_id for q in first.questions]
    again, _ = make()
    second = await plan(again, [], exclude=exclude)
    assert not {q.bank_id for q in second.questions} & set(exclude)


async def test_long_documents_are_split_into_extraction_calls_within_the_budget() -> None:
    long_text = "\n".join(f"{i}번째 줄: " + "가나다라마바사" * 30 for i in range(40))
    session = happy_session()
    interview, _ = make(session)
    await plan(interview, [doc(long_text)])
    assert session.count("materials") > 1
    assert all(len(p) < 6000 for n, p in session.calls)


async def test_model_unavailable_maps_to_interview_model_unavailable() -> None:
    error = AppError("LOCAL_MODEL_UNAVAILABLE", "준비해 주세요.", 503)
    interview, _ = make(error=error)
    with pytest.raises(AppError) as raised:
        await plan(interview)
    assert (raised.value.code, raised.value.status_code) == ("INTERVIEW_MODEL_UNAVAILABLE", 503)


async def test_server_never_ready_maps_to_plan_failed_504() -> None:
    interview, _ = make(error=asyncio.TimeoutError())
    with pytest.raises(AppError) as raised:
        await plan(interview)
    assert (raised.value.code, raised.value.status_code) == ("INTERVIEW_PLAN_FAILED", 504)


async def test_server_start_failure_maps_to_plan_failed() -> None:
    interview, _ = make(error=ValueError("Native generation model failed to start"))
    with pytest.raises(AppError) as raised:
        await plan(interview)
    assert (raised.value.code, raised.value.status_code) == ("INTERVIEW_PLAN_FAILED", 503)


async def test_timeout_falls_back_to_common_questions_and_reaps_the_model() -> None:
    class SlowSession(FakeSession):
        async def complete_json(self, *args, **kwargs):
            await asyncio.sleep(10)

    llm = FakeLlm(SlowSession({}))
    interview = InterviewLlm(llm, rng=random.Random(1), timeout_seconds=0.05)
    started = time.monotonic()
    result = await plan(interview)
    assert time.monotonic() - started < 2  # the 10s model call was cut off by the budget
    assert result.warnings == ["document_questions_failed"]
    assert kinds(result) == ["common"] * 9
    assert llm.entered == llm.exited == 1


class FakeClock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


async def test_server_start_up_counts_against_the_budget() -> None:
    clock = FakeClock()
    session = happy_session()

    class SlowStartLlm(FakeLlm):
        @asynccontextmanager
        async def loaded(self):
            async with super().loaded() as loaded:
                clock.now += 100  # start-up alone exceeds the 25s budget
                yield loaded

    llm = SlowStartLlm(session)
    interview = InterviewLlm(llm, rng=random.Random(1), timeout_seconds=25, clock=clock)
    result = await plan(interview)
    assert session.calls == []
    assert result.warnings == ["document_questions_failed"]
    assert llm.entered == llm.exited == 1


async def test_extraction_stops_at_sixty_percent_of_the_budget() -> None:
    clock = FakeClock()
    session = happy_session()
    session.on_call = lambda: setattr(clock, "now", clock.now + 10)  # each call costs 10s
    long_text = DOCUMENT + "\n".join(f"{i}번째 줄: " + "가나다라마바사" * 30 for i in range(40))
    llm = FakeLlm(session)
    interview = InterviewLlm(llm, rng=random.Random(1), timeout_seconds=25, clock=clock)
    result = await plan(interview, [doc(long_text)])
    # 15s of 25s is the extraction share: two extraction calls (20s), then questions.
    assert session.count("materials") == 2 and session.count("questions") == 1
    assert kinds(result).count("document") == 4 and result.warnings == []
    assert llm.entered == llm.exited == 1


async def test_budget_spent_before_the_question_call_falls_back() -> None:
    clock = FakeClock()
    session = happy_session()
    session.on_call = lambda: setattr(clock, "now", clock.now + 100)
    interview = InterviewLlm(
        FakeLlm(session), rng=random.Random(1), timeout_seconds=25, clock=clock
    )
    result = await plan(interview)
    assert session.count("questions") == 0
    assert result.warnings == ["document_questions_failed"]
    assert kinds(result) == ["common"] * 9


async def test_retry_uses_another_seed_and_a_correction_hint() -> None:
    fake = {"items": [{"kind": "project", "quote": "없는 문장", "summary": "x"}]}
    session = FakeSession({"materials": [fake, MATERIALS], "questions": QUESTIONS})
    interview, _ = make(session)
    await plan(interview)
    first, retry = [p for n, p in session.calls if n == "materials"]
    assert retry != first and retry.startswith(first) and "그대로 복사" in retry
    assert session.seeds[0] != session.seeds[1]


async def test_question_retry_names_the_rejection_reason() -> None:
    bad = {"questions": [question("job", 1, "A는 무엇인가요? B는 무엇인가요?")]}
    session = FakeSession({"materials": MATERIALS, "questions": [bad, QUESTIONS]})
    interview, _ = make(session)
    result = await plan(interview)
    first, retry = [p for n, p in session.calls if n == "questions"]
    assert retry != first and "한 질문에는 하나만" in retry
    assert len([q for q in result.questions if q.kind == "document"]) == 4


async def test_intent_is_sanitized() -> None:
    items = [dict(q) for q in QUESTIONS["questions"]]
    items[0]["intent"] = "  가족 관계를 확인한다.  "
    items[1]["intent"] = "  역할을 확인한다.  "
    items[2]["intent"] = "가" * 300
    items[3]["intent"] = ""
    interview, _ = make(FakeSession({"materials": MATERIALS, "questions": {"questions": items}}))
    result = await plan(interview)
    intents = {q.text: q.intent for q in result.questions if q.kind == "document"}
    assert "가족" not in " ".join(intents.values())
    assert intents[items[1]["text"]] == "역할을 확인한다."
    assert len(intents[items[2]["text"]]) <= 100
    assert all(intents.values())


async def test_blank_job_is_allowed() -> None:
    session = happy_session()
    interview, _ = make(session)
    result = await interview.plan([doc()], None, Composition(), [], None)
    assert len(result.questions) == 9
    prompt = next(p for n, p in session.calls if n == "questions")
    assert "지정 없음" in prompt


async def test_duplicate_questions_for_one_material_and_subtype_keep_one() -> None:
    duplicated = {
        "questions": [
            # Each duplicate precedes the other valid question of its subtype, so the per-subtype
            # cap cannot hide a missing dedupe.
            question("job", 1, "추론 서버를 만들 때 FastAPI를 선택한 이유는 무엇인가요?"),
            question("job", 1, "추론 서버에서 다른 프레임워크를 고려했다면 무엇이었나요?"),
            question(
                "job", 0, "객체 검출 연구의 데이터 증강 기법을 직무에 어떻게 적용하시겠습니까?"
            ),
            question(
                "experience", 0, "객체 검출 연구에서 본인이 맡은 역할과 직접 한 일은 무엇인가요?"
            ),
            question("experience", 0, "객체 검출 연구에서 가장 중요했던 본인의 결정은 무엇인가요?"),
            question("experience", 2, "동아리 스터디를 운영하며 새로 배운 점은 무엇이었나요?"),
        ]
    }
    interview, _ = make(FakeSession({"materials": MATERIALS, "questions": duplicated}))
    result = await plan(interview)
    docs = [q for q in result.questions if q.kind == "document"]
    keys = [(q.subtype, q.source_quote) for q in docs]
    assert len(keys) == len(set(keys)) == 4


async def test_rubric_items_per_subtype() -> None:
    interview, _ = make()
    result = await plan(interview)
    expected = {
        "job": ["understanding", "reasoning"],
        "experience": ["specificity", "reasoning", "learning"],
    }
    for q in result.questions:
        if q.kind == "document":
            assert [r.value for r in q.rubric_items] == expected[q.subtype]


async def test_exclude_order_is_kept_with_duplicates() -> None:
    closing = Composition(
        common_basic=0,
        personality_behavioral=0,
        personality_situational=0,
        job=0,
        experience=0,
        include_closing=True,
    )
    interview, _ = make()
    # basic-closing-2 is the oldest by last use: the duplicate must not move basic-closing-1 up.
    others = [f"basic-closing-{n}" for n in range(3, 11)]
    exclude = ["basic-closing-1", "basic-closing-2", "basic-closing-1", *others]
    result = await interview.plan([], None, closing, exclude, None)
    assert [q.bank_id for q in result.questions] == ["basic-closing-2"]
