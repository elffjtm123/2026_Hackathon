"""InterviewRun: thin glue between one realtime session and an InterviewConductor.

No decisions live here. The pipeline feeds it voiced/unvoiced frames, final transcripts and the
number of finals still on their way; a 200 ms task ticks the conductor; the conductor's Actions
become protocol-2 `interview.*` events. All times are session milliseconds. `clock` (the
pipeline's `elapsed_ms`) is wall time on that scale; it is only the fallback of the
conductor's own clock, see `_now`.

Clock: frames and utterances are stamped on the audio timeline (`audio_origin_ms` plus the
sample offset) but reach the server late (capture starts after `session.running`, 200 ms
chunks, transport, queues). If the conductor ran on wall time, "now - last voiced end" would
never fall below that lag and the time-limit and silence rules would fire mid-utterance. So
the conductor's `now` is the latest observed frame end, never further than
`TurnRules.stall_allowance_ms` behind wall time (so questions still advance if audio stops
entirely), and never goes backwards.

All outgoing events pass one outbox that a single task drains, so they leave in the order the
conductor produced them even though frames are observed from synchronous callbacks. The task
wakes at once when something was queued and otherwise ticks every `tick_seconds`.

Round 2 (follow-up questions after a round break) is not wired yet: `_on_round_finished` is the
seam where step 7 suspends the pipeline, generates follow-ups and calls `conductor.add_questions`.
"""

from __future__ import annotations

import asyncio
import logging
from collections import deque
from collections.abc import Awaitable, Callable
from typing import Any

from app.modules.interview.composition import TurnRules
from app.modules.interview.conductor import (
    Action,
    Advanced,
    HideQuestion,
    InterviewConductor,
    ReplayRejected,
    RoundFinished,
    ShowQuestion,
)
from app.modules.interview.questions import FinalUtterance, ItemRecord, PlannedQuestion

logger = logging.getLogger(__name__)

Emit = Callable[[str, dict[str, Any]], Awaitable[None]]


class InterviewRun:
    def __init__(
        self,
        questions: list[PlannedQuestion],
        rules: TurnRules,
        *,
        clock: Callable[[], int],
        emit: Emit,
        pending_finals: Callable[[], int],
        save_items: Callable[[list[ItemRecord]], None],
        tick_seconds: float = 0.2,
    ) -> None:
        self._conductor = InterviewConductor(questions, rules)
        self._stall_allowance_ms = rules.stall_allowance_ms
        self._latest_frame_end: int | None = None
        self._last_frame_wall = 0  # wall time of the latest observed frame
        self._lag_warned = False
        self._last_now = 0
        self.started = False
        self._clock = clock
        self._emit = emit
        self._pending_finals = pending_finals
        self._save_items = save_items
        self._tick_seconds = tick_seconds
        self.stop_flush_seconds = 1.0
        self._total = {q.round: sum(1 for p in questions if p.round == q.round) for q in questions}
        self._shown_index: dict[str, int] = {}  # question id -> 1-based index within its round
        self._round_count: dict[int, int] = {}
        self._current_id: str | None = None
        self._by_id = {q.id: q for q in questions}
        self._outbox: deque[tuple[str, dict[str, Any]] | RoundFinished] = deque()
        self._flush_lock = asyncio.Lock()
        self._wakeup = asyncio.Event()
        self._task: asyncio.Task[None] | None = None
        self._stopped = False
        self._failed = False

    @property
    def running(self) -> bool:
        return self._task is not None and not self._task.done()

    # -- lifecycle ---------------------------------------------------------------

    def _now(self) -> int:
        """The conductor's clock: audio timeline, bounded behind wall time, monotonic."""
        candidate = self._clock() - self._stall_allowance_ms
        if self._latest_frame_end is not None:
            candidate = max(candidate, self._latest_frame_end)
        wall = self._clock()
        if (
            not self._lag_warned
            and self._latest_frame_end is not None
            and wall - self._latest_frame_end > self._stall_allowance_ms
            and wall - self._last_frame_wall <= self._stall_allowance_ms  # frames still arrive
        ):
            self._lag_warned = True
            logger.warning(
                "interview_frame_lag_exceeds_allowance",
                extra={
                    "lag_ms": wall - self._latest_frame_end,
                    "stall_allowance_ms": self._stall_allowance_ms,
                },
            )
        self._last_now = max(self._last_now, candidate)
        return self._last_now

    async def start(self, origin_ms: int | None = None) -> None:
        """Show the first question. `origin_ms` is the audio origin (the session's first audio
        time), so the first frames are not older than the question; default is wall time."""
        if self.started or self._stopped:
            return
        self.started = True
        self._last_now = origin_ms if origin_ms is not None else self._clock()
        self._guarded(lambda: self._enqueue(self._conductor.start(self._last_now)))
        await self.step(tick=False)  # the first question is out before `start` returns
        if not self._stopped and not self._failed:
            self._task = asyncio.create_task(self._loop(), name="interview-run")

    async def stop(self) -> None:
        """End the interview: stop the tick task, end the current question as "stopped"."""
        if self._stopped:
            return
        self._stopped = True
        task, self._task = self._task, None
        if task is not None:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        self._guarded(lambda: self._enqueue(self._conductor.stop(self._now())))
        try:
            await asyncio.wait_for(self.step(tick=False), self.stop_flush_seconds)
        except (TimeoutError, asyncio.TimeoutError):
            logger.warning("interview_stop_flush_timeout")
        except Exception:
            logger.exception("interview_stop_flush_failed")

    def finalize(self) -> list[dict[str, Any]]:
        """Save the item records to the store and return them as report entries.

        Repeatable (the latest call wins): the pipeline calls it for the report after its
        drain, and the socket calls it again on every exit path. Ends the interview first if
        `stop` has not run, without emitting events.
        """
        if not self._stopped:
            self._stopped = True
            task, self._task = self._task, None
            if task is not None:
                task.cancel()  # no await here; stop() is the clean path
            self._guarded(lambda: self._conductor.stop(self._now()))
        items = self._conductor.items()
        try:
            self._save_items(items)
        except Exception:
            logger.exception("interview_save_items_failed")
        return [_report_item(item) for item in items]

    # -- inputs from the pipeline ------------------------------------------------

    def observe_frame(self, start_ms: int, end_ms: int, voiced: bool) -> None:
        if self._stopped or self._failed:
            return
        if self._latest_frame_end is None or end_ms > self._latest_frame_end:
            self._latest_frame_end = end_ms
        self._last_frame_wall = self._clock()
        self._guarded(lambda: self._enqueue(self._conductor.on_frame(start_ms, end_ms, voiced)))

    def on_final(self, utterance: FinalUtterance) -> None:
        """A final transcript; late ones after `stop` still attach to the question they began in."""
        if self._failed:
            return
        self._guarded(lambda: self._enqueue(self._conductor.on_final(utterance)))

    async def replay(self, question_id: str) -> None:
        """The client asks to see the question again; only the question on screen's turn counts."""
        if self._stopped or self._failed:
            return
        if question_id != self._current_id:
            self._enqueue([ReplayRejected(question_id)])
        else:
            self._guarded(lambda: self._enqueue(self._conductor.on_replay(self._now())))
        await self.step(tick=False)

    async def step(self, *, tick: bool = True) -> None:
        """Tick the conductor at the current time (unless `tick` is False) and send what's due."""
        if tick and not self._stopped and not self._failed:
            self._guarded(
                lambda: self._enqueue(self._conductor.tick(self._now(), self._pending_finals()))
            )
        async with self._flush_lock:
            while self._outbox:
                entry = self._outbox.popleft()
                if isinstance(entry, RoundFinished):
                    await self._emit("interview.finished", {})
                    await self._on_round_finished(entry.round)
                else:
                    await self._emit(*entry)

    # -- internals ---------------------------------------------------------------

    def _guarded(self, work: Callable[[], object]) -> None:
        """A conductor bug must not reach the audio worker; after one the run goes quiet."""
        try:
            work()
        except Exception:
            self._failed = True
            logger.exception("interview_run_failed")

    async def _loop(self) -> None:
        try:
            while True:
                await self.step()
                # Not `wait_for(event.wait())`: before Python 3.12 it can swallow a cancel that
                # arrives together with the event, leaving a task that `stop` waits on forever.
                timer = asyncio.get_running_loop().call_later(self._tick_seconds, self._wakeup.set)
                try:
                    await self._wakeup.wait()
                finally:
                    timer.cancel()
                    self._wakeup.clear()
        except asyncio.CancelledError:
            raise
        except Exception:
            self._failed = True
            logger.exception("interview_tick_loop_failed")

    def _enqueue(self, actions: list[Action]) -> None:
        for action in actions:
            if isinstance(action, RoundFinished):
                self._outbox.append(action)
            else:
                self._outbox.append(self._to_event(action))
        if actions:
            self._wakeup.set()

    async def _on_round_finished(self, round_: int) -> None:
        """Seam for step 7, called right after `interview.finished` went out for `round_`.

        Round 1 simply ends the interview for now; step 7 will start the round break here
        (and send `interview.finished` only when no follow-ups follow).
        """

    def _to_event(
        self, action: ShowQuestion | HideQuestion | Advanced | ReplayRejected
    ) -> tuple[str, dict[str, Any]]:
        if isinstance(action, ShowQuestion):
            return "interview.question", self._question_data(action)
        if isinstance(action, HideQuestion):
            return "interview.question_hidden", {"question_id": action.id}
        if isinstance(action, Advanced):
            if self._current_id == action.id:
                self._current_id = None
            return "interview.advanced", {"question_id": action.id, "reason": action.reason}
        return "interview.replay_rejected", {"question_id": action.id}

    def _question_data(self, action: ShowQuestion) -> dict[str, Any]:
        question = self._by_id[action.id]
        replay = action.id in self._shown_index
        if not replay:
            count = self._round_count.get(question.round, 0) + 1
            self._round_count[question.round] = count
            self._shown_index[action.id] = count
        self._current_id = action.id
        return {
            "question_id": action.id,
            "round": question.round,
            "index": self._shown_index[action.id],
            "total": self._total.get(question.round, 0),
            "text": action.text,
            "reading_ms": action.reading_ms,
            "answer_limit_ms": action.answer_limit_ms,
            "replay_available": not replay,
        }


def _report_item(item: ItemRecord) -> dict[str, Any]:
    return {
        "question_id": item.question.id,
        "round": item.question.round,
        "text": item.question.text,
        "shown_ms": item.shown_ms,
        "answer_started_ms": item.answer_started_ms,
        "ended_ms": item.ended_ms,
        "advance_reason": item.advance_reason,
        "replay_used": item.replay_used,
        "transcript": item.transcript,
        "utterances": [
            {
                "utterance_id": u.utterance_id,
                "start_ms": u.start_ms,
                "end_ms": u.end_ms,
                "text": u.text,
                "voiced_ms": u.voiced_ms,
            }
            for u in item.utterances
        ],
    }
