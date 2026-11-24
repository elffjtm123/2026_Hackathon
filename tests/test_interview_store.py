"""Seam: InterviewStore (in-memory plans with expiry and a size cap)."""

import pytest

from app.core.errors import AppError
from app.modules.interview.plan import InterviewPlan
from app.modules.interview.questions import PlannedQuestion
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
