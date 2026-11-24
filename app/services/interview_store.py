"""In-memory interview state; nothing is persisted and a restart clears it.

Only plans live here for now. Later steps add the attached session, item records and the
evaluation to `InterviewState` and the matching setters on the store.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass
from uuid import uuid4

from app.core.errors import AppError
from app.modules.interview.plan import InterviewPlan


@dataclass
class InterviewState:
    interview_id: str
    plan: InterviewPlan
    created_at: float


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
        self._states[interview_id] = InterviewState(interview_id, plan, self._clock())
        while len(self._states) > self._max:
            del self._states[next(iter(self._states))]
        return interview_id

    def get(self, interview_id: str) -> InterviewState:
        self._expire()
        state = self._states.get(interview_id)
        if state is None:
            raise AppError("INTERVIEW_NOT_FOUND", "면접 정보를 찾을 수 없습니다.", 404)
        return state

    def discard(self, interview_id: str) -> None:
        self._states.pop(interview_id, None)

    def _expire(self) -> None:
        cutoff = self._clock() - self._ttl
        for interview_id in [i for i, s in self._states.items() if s.created_at < cutoff]:
            del self._states[interview_id]
