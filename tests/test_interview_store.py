"""Seam: InterviewStore (in-memory plans with expiry and a size cap)."""

from uuid import uuid4

import pytest

from app.core.errors import AppError
from app.modules.interview.evaluation import EvaluationSummary, InterviewEvaluation
from app.modules.interview.plan import InterviewPlan
from app.modules.interview.questions import ItemRecord, PlannedQuestion
from app.services.interview_store import InterviewStore


class Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def plan(text: str = "질문") -> InterviewPlan:
    return InterviewPlan(
        questions=[PlannedQuestion(id="q1", kind="common", subtype="x", text=text)]
    )


def test_create_then_get_returns_the_plan_under_a_fresh_id() -> None:
    store = InterviewStore(ttl_seconds=60, max_entries=5, clock=Clock())
    first, second = store.create(plan("a")), store.create(plan("b"))
    assert first != second
    assert store.get(first).plan.questions[0].text == "a"
    assert store.get(second).plan.questions[0].text == "b"


def test_unknown_id_is_not_found() -> None:
    store = InterviewStore(ttl_seconds=60, max_entries=5, clock=Clock())
    with pytest.raises(AppError) as error:
        store.get("missing")
    assert (error.value.code, error.value.status_code) == ("INTERVIEW_NOT_FOUND", 404)


def test_entries_expire_after_the_ttl() -> None:
    clock = Clock()
    store = InterviewStore(ttl_seconds=60, max_entries=5, clock=clock)
    interview_id = store.create(plan())
    clock.now += 59
    assert store.get(interview_id) is not None
    clock.now += 2
    with pytest.raises(AppError):
        store.get(interview_id)
    assert len(store) == 0


def test_expired_entries_are_dropped_when_creating() -> None:
    clock = Clock()
    store = InterviewStore(ttl_seconds=60, max_entries=5, clock=clock)
    store.create(plan())
    clock.now += 61
    store.create(plan())
    assert len(store) == 1


def test_oldest_entry_is_evicted_past_max_entries() -> None:
    clock = Clock()
    store = InterviewStore(ttl_seconds=600, max_entries=2, clock=clock)
    ids = []
    for _ in range(3):
        ids.append(store.create(plan()))
        clock.now += 1
    assert len(store) == 2
    with pytest.raises(AppError):
        store.get(ids[0])
    assert store.get(ids[2]) is not None


def test_discard_removes_and_is_idempotent() -> None:
    store = InterviewStore(ttl_seconds=60, max_entries=5, clock=Clock())
    interview_id = store.create(plan())
    store.discard(interview_id)
    store.discard(interview_id)
    assert len(store) == 0


# --- attaching a realtime session (spec 4.7) ---


def three_question_plan() -> InterviewPlan:
    return InterviewPlan(
        questions=[
            PlannedQuestion(id=f"q{n}", kind="common", subtype="x", text=f"질문 {n}")
            for n in (1, 2, 3)
        ]
    )


def attach_error(store: InterviewStore, interview_id: str, ids: list[str]) -> AppError:
    with pytest.raises(AppError) as error:
        store.attach_session(interview_id, uuid4(), ids)
    return error.value


def test_attach_returns_the_chosen_questions_in_the_users_order() -> None:
    store = InterviewStore(ttl_seconds=60, max_entries=5, clock=Clock())
    interview_id = store.create(three_question_plan())
    session_id = uuid4()
    chosen = store.attach_session(interview_id, session_id, ["q3", "q1"])
    assert [q.id for q in chosen] == ["q3", "q1"]
    state = store.get(interview_id)
    assert state.session_id == session_id and state.question_ids == ["q3", "q1"]


def test_attach_to_unknown_interview_is_not_found() -> None:
    store = InterviewStore(ttl_seconds=60, max_entries=5, clock=Clock())
    assert attach_error(store, "missing", ["q1"]).code == "INTERVIEW_NOT_FOUND"


@pytest.mark.parametrize("ids", [[], ["q1", "q1"], ["q1", "nope"]])
def test_attach_rejects_empty_duplicate_or_foreign_question_ids(ids: list[str]) -> None:
    store = InterviewStore(ttl_seconds=60, max_entries=5, clock=Clock())
    interview_id = store.create(three_question_plan())
    assert attach_error(store, interview_id, ids).code == "INVALID_SETTINGS"
    # The failed attempt must leave the plan usable.
    assert [q.id for q in store.attach_session(interview_id, uuid4(), ["q2"])] == ["q2"]


def test_a_plan_attaches_to_one_session_only() -> None:
    store = InterviewStore(ttl_seconds=60, max_entries=5, clock=Clock())
    interview_id = store.create(three_question_plan())
    store.attach_session(interview_id, uuid4(), ["q1"])
    error = attach_error(store, interview_id, ["q1"])
    assert (error.code, error.status_code) == ("INTERVIEW_ALREADY_STARTED", 409)


def test_detach_frees_the_plan_for_a_new_session() -> None:
    store = InterviewStore(ttl_seconds=60, max_entries=5, clock=Clock())
    interview_id = store.create(three_question_plan())
    session_id = uuid4()
    store.attach_session(interview_id, session_id, ["q1"])
    store.detach_session(interview_id, uuid4())  # someone else's session: no effect
    assert attach_error(store, interview_id, ["q1"]).code == "INTERVIEW_ALREADY_STARTED"
    store.detach_session(interview_id, session_id)
    store.attach_session(interview_id, uuid4(), ["q2"])


def test_attached_plan_does_not_expire_mid_session_but_does_after_the_items_are_saved() -> None:
    clock = Clock()
    store = InterviewStore(ttl_seconds=60, max_entries=5, clock=clock)
    interview_id = store.create(three_question_plan())
    store.attach_session(interview_id, uuid4(), ["q1"])
    clock.now += 3600
    assert store.get(interview_id) is not None  # a long session is still running
    store.save_items(interview_id, [])
    clock.now += 59
    assert store.get(interview_id) is not None  # the TTL restarts when the session ends
    clock.now += 2
    with pytest.raises(AppError):
        store.get(interview_id)


def test_save_items_keeps_the_latest_records() -> None:
    store = InterviewStore(ttl_seconds=60, max_entries=5, clock=Clock())
    interview_id = store.create(three_question_plan())
    store.attach_session(interview_id, uuid4(), ["q1"])
    question = store.get(interview_id).plan.questions[0]
    record = ItemRecord(question, 0, None, 10, "stopped", False, [], "")
    store.save_items(interview_id, [record])
    store.save_items(interview_id, [record, record])
    assert len(store.get(interview_id).items) == 2


def test_save_items_for_unknown_interview_is_not_found() -> None:
    store = InterviewStore(ttl_seconds=60, max_entries=5, clock=Clock())
    with pytest.raises(AppError) as error:
        store.save_items("missing", [])
    assert error.value.code == "INTERVIEW_NOT_FOUND"


def test_eviction_never_drops_a_plan_with_a_running_session() -> None:
    clock = Clock()
    store = InterviewStore(ttl_seconds=600, max_entries=2, clock=clock)
    running = store.create(three_question_plan())
    store.attach_session(running, uuid4(), ["q1"])
    others = []
    for _ in range(3):
        clock.now += 1
        others.append(store.create(plan()))
    assert store.get(running) is not None
    assert len(store) == 2


# --- evaluation (step 8) ---


def finished(store: InterviewStore, clock: Clock | None = None) -> str:
    interview_id = store.create(three_question_plan())
    store.attach_session(interview_id, uuid4(), ["q1"])
    store.save_items(interview_id, [])
    return interview_id


def evaluation() -> InterviewEvaluation:
    return InterviewEvaluation([], None, EvaluationSummary(), "m", 1.0)


def test_items_saved_tells_a_finished_session_from_one_that_never_ran() -> None:
    store = InterviewStore(ttl_seconds=60, max_entries=5, clock=Clock())
    never = store.create(three_question_plan())
    assert not store.get(never).items_saved
    assert store.get(finished(store)).items_saved  # also with an empty item list


def test_set_evaluation_keeps_the_result_and_ends_the_running_flag() -> None:
    store = InterviewStore(ttl_seconds=60, max_entries=5, clock=Clock())
    interview_id = finished(store)
    store.begin_evaluation(interview_id)
    assert store.get(interview_id).evaluating
    result = evaluation()
    store.set_evaluation(interview_id, result)
    state = store.get(interview_id)
    assert state.evaluation is result and state.evaluation is not None
    store.end_evaluation(interview_id)
    assert not store.get(interview_id).evaluating


def test_set_evaluation_for_unknown_interview_is_not_found() -> None:
    store = InterviewStore(ttl_seconds=60, max_entries=5, clock=Clock())
    with pytest.raises(AppError) as error:
        store.set_evaluation("missing", evaluation())
    assert error.value.code == "INTERVIEW_NOT_FOUND"
    store.end_evaluation("missing")  # a vanished entry is not an error here


def test_a_delivered_result_is_removed_thirty_minutes_after_delivery() -> None:
    clock = Clock()
    store = InterviewStore(ttl_seconds=2 * 3600, max_entries=5, clock=clock)
    interview_id = finished(store)
    store.set_evaluation(interview_id, evaluation())
    clock.now += 3000  # an undelivered result still lives by the plan TTL
    assert store.get(interview_id) is not None
    store.mark_delivered(interview_id)
    clock.now += 1799
    store.mark_delivered(interview_id)  # a replay does not extend the lifetime
    assert store.get(interview_id) is not None
    clock.now += 2
    with pytest.raises(AppError):
        store.get(interview_id)


def test_the_delivered_lifetime_is_configurable() -> None:
    clock = Clock()
    store = InterviewStore(ttl_seconds=3600, max_entries=5, clock=clock, delivered_ttl_seconds=10)
    interview_id = finished(store)
    store.set_evaluation(interview_id, evaluation())
    store.mark_delivered(interview_id)
    clock.now += 11
    assert len(store) == 0


def test_a_running_evaluation_is_never_expired_or_evicted() -> None:
    clock = Clock()
    store = InterviewStore(ttl_seconds=60, max_entries=2, clock=clock)
    interview_id = finished(store)
    store.begin_evaluation(interview_id)
    clock.now += 3600
    assert store.get(interview_id) is not None
    for _ in range(3):
        clock.now += 1
        store.create(plan())
    assert store.get(interview_id) is not None
    store.end_evaluation(interview_id)
    clock.now += 61
    with pytest.raises(AppError):
        store.get(interview_id)
