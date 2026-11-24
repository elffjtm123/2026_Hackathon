"""In-memory interview state; nothing is persisted and a restart clears it.

A plan holds the questions, then the realtime session attached to it and the item records that
session saved. Step 8 adds the evaluation and its setter.

Expiry: `ttl_seconds` counts from the last touch (create, attach, save_items). A plan with a
running session (attached, items not yet saved) never expires and is never evicted, however long
the session lasts; its TTL restarts when the session saves its items or detaches.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass, field
from uuid import UUID, uuid4

from app.core.errors import AppError
from app.modules.interview.plan import InterviewPlan
from app.modules.interview.questions import ItemRecord, PlannedQuestion


@dataclass
class InterviewState:
    interview_id: str
    plan: InterviewPlan
    created_at: float
    touched_at: float = 0.0  # TTL anchor; set to created_at by the store
    session_id: UUID | None = None
    question_ids: list[str] = field(default_factory=list)
    items: list[ItemRecord] = field(default_factory=list)
    running: bool = False  # a session is attached and has not saved its items yet


class InterviewStore:
    def __init__(
        self,
        ttl_seconds: float,
        max_entries: int,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._ttl = ttl_seconds
        self._max = max_entries
        self._clock = clock
        self._states: dict[str, InterviewState] = {}  # insertion order = creation order

    def __len__(self) -> int:
        self._expire()
        return len(self._states)

    def create(self, plan: InterviewPlan) -> str:
        self._expire()
        interview_id = uuid4().hex
        now = self._clock()
        self._states[interview_id] = InterviewState(interview_id, plan, now, now)
        while len(self._states) > self._max:
            evictable = next((i for i, s in self._states.items() if not s.running), None)
            if evictable is None:
                break  # only running sessions are left; the cap yields to them
            del self._states[evictable]
        return interview_id

    def get(self, interview_id: str) -> InterviewState:
        self._expire()
        state = self._states.get(interview_id)
        if state is None:
            raise AppError("INTERVIEW_NOT_FOUND", "면접 정보를 찾을 수 없습니다.", 404)
        return state

    def attach_session(
        self, interview_id: str, session_id: UUID, question_ids: list[str]
    ) -> list[PlannedQuestion]:
        """Bind a realtime session to the chosen questions; returns them in the user's order.

        Validates everything before changing anything, so a rejected attempt leaves the plan
        usable. A plan belongs to one session only, even after that session has ended.
        """
        state = self.get(interview_id)
        if not question_ids or len(set(question_ids)) != len(question_ids):
            raise AppError("INVALID_SETTINGS", "질문 선택이 올바르지 않습니다.", 422)
        by_id = {q.id: q for q in state.plan.questions}
        if any(question_id not in by_id for question_id in question_ids):
            raise AppError("INVALID_SETTINGS", "계획에 없는 질문이 포함되어 있습니다.", 422)
        if state.session_id is not None:
            raise AppError("INTERVIEW_ALREADY_STARTED", "이미 시작한 면접입니다.", 409)
        state.session_id = session_id
        state.question_ids = list(question_ids)
        state.running = True
        state.touched_at = self._clock()
        return [by_id[question_id] for question_id in question_ids]

    def detach_session(self, interview_id: str, session_id: UUID) -> None:
        """Undo `attach_session` for a session that never ran (failed start). Others' no-op."""
        state = self._states.get(interview_id)
        if state is None or state.session_id != session_id:
            return
        state.session_id = None
        state.question_ids = []
        state.running = False
        state.touched_at = self._clock()

    def save_items(self, interview_id: str, items: list[ItemRecord]) -> None:
        """Keep the session's item records (latest call wins) and end its running state."""
        state = self.get(interview_id)
        state.items = list(items)
        state.running = False
        state.touched_at = self._clock()

    def discard(self, interview_id: str) -> None:
        self._states.pop(interview_id, None)

    def _expire(self) -> None:
        cutoff = self._clock() - self._ttl
        for interview_id in [
            i for i, s in self._states.items() if not s.running and s.touched_at < cutoff
        ]:
            del self._states[interview_id]
