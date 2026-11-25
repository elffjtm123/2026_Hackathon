"""InterviewConductor: the interviewer's judgement as a pure state machine.

Time is injected (session milliseconds). The conductor knows nothing about sockets, timers or
models: callers feed frames, final transcripts and ticks, and carry out the returned Actions.

Rules in short (values come from TurnRules):
- The question hides when its reading time ends or on the first voiced frame, whichever first.
- Silence advances only after `silence_ms` without voice AND `min_answer_ms` of answer time.
- The time limit advances at the end of the current utterance (last voiced end + endpoint).
- No response is measured from the end of the first reading time.
- One replay per question; the answer, silence and no-response clocks stop while it is shown.
  Speaking during a replay hides it and resumes the clocks, but not before it has been on
  screen `replay_min_visible_ms` (the hide waits for that, the reading end still hides it).
- Once an advance reason fires it is committed: the conductor waits for `pending_finals == 0`
  (at most `final_wait_cap_ms`) before advancing. Later finals still attach to the original
  question because they are assigned by `start_ms` to the question whose window contains it.

Known split: speech running past the segmenter's 8 s maximum across a question start is cut
into segments; the continuation segment (no pre-roll) may be assigned to the next question by
`start_ms` although its frames were ignored as carry-over (no answer start, no hide).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.modules.interview.composition import TurnRules
from app.modules.interview.questions import (
    AdvanceReason,
    FinalUtterance,
    ItemRecord,
    PlannedQuestion,
)


@dataclass(frozen=True)
class ShowQuestion:
    id: str
    text: str
    reading_ms: int
    answer_limit_ms: int


@dataclass(frozen=True)
class HideQuestion:
    id: str


@dataclass(frozen=True)
class Advanced:
    id: str
    reason: AdvanceReason


@dataclass(frozen=True)
class RoundFinished:
    round: int


@dataclass(frozen=True)
class ReplayRejected:
    id: str


Action = ShowQuestion | HideQuestion | Advanced | RoundFinished | ReplayRejected


@dataclass
class _Slot:
    """Mutable state of one question."""

    question: PlannedQuestion
    shown_ms: int
    reading_end_ms: int  # when the question currently on screen hides
    first_reading_end_ms: int
    visible: bool = True
    visible_since_ms: int = 0  # start of the current on-screen period (first show or replay)
    hide_deferred: bool = False  # voice arrived during the replay's minimum display time
    answer_started_ms: int | None = None
    last_voiced_end_ms: int | None = None
    replay_used: bool = False
    pauses: list[list[int]] = field(default_factory=list)  # [start, end) replay windows
    candidate: tuple[AdvanceReason, int] | None = None  # (reason, decided_at_ms)
    ended_ms: int | None = None
    reason: AdvanceReason | None = None
    utterances: list[FinalUtterance] = field(default_factory=list)

    def eff(self, t: int) -> int:
        """`t` minus the replay time before it: the clock the answer rules run on."""
        paused = sum(max(0, min(t, end) - start) for start, end in self.pauses)
        return t - paused


class InterviewConductor:
    def __init__(self, questions: list[PlannedQuestion], rules: TurnRules) -> None:
        self._rules = rules
        self._queue: list[PlannedQuestion] = list(questions)
        self._slots: list[_Slot] = []  # every question shown so far, in order
        self._current: _Slot | None = None
        self._stopped = False
        self._last_round = 1
        # Latest run of contiguous voiced frames, tracked across questions (for carry-over).
        self._run_start_ms: int | None = None
        self._run_end_ms: int | None = None

    # -- inputs -----------------------------------------------------------------

    def start(self, now_ms: int) -> list[Action]:
        return self._show_next(now_ms) or [RoundFinished(self._last_round)]

    def on_frame(self, start_ms: int, end_ms: int, voiced: bool) -> list[Action]:
        if not voiced:
            return []
        self._track_run(start_ms, end_ms)
        slot = self._current
        if slot is None or start_ms < slot.shown_ms or self._is_carry_over(slot, start_ms):
            return []
        actions: list[Action] = []
        if slot.answer_started_ms is None:
            slot.answer_started_ms = start_ms
        slot.last_voiced_end_ms = max(slot.last_voiced_end_ms or 0, end_ms)
        # A frame that began before the question (re)appeared is lagging speech, not a reaction.
        if slot.visible and start_ms >= slot.visible_since_ms:
            if slot.replay_used and start_ms < self._replay_min_end(slot):
                slot.hide_deferred = True  # the tick hides it when the minimum has passed
                return actions
            slot.visible = False
            actions.append(HideQuestion(slot.question.id))
            # Speaking during a replay ends its pause at the moment speech began.
            for window in slot.pauses:
                if window[0] <= start_ms < window[1]:
                    window[1] = max(start_ms, window[0])
        return actions

    def on_final(self, utterance: FinalUtterance) -> list[Action]:
        """Attach a transcript to the question whose window contains its start_ms."""
        # The segmenter's pre-roll puts start_ms before the first voiced frame.
        start = min(utterance.start_ms + self._rules.pre_roll_ms, utterance.end_ms)
        for slot in self._slots:
            end = slot.ended_ms if slot.ended_ms is not None else float("inf")
            if slot.shown_ms <= start < end:
                slot.utterances.append(utterance)
                break
        return []

    def on_replay(self, now_ms: int) -> list[Action]:
        slot = self._current
        if slot is None:
            return []
        if slot.replay_used or slot.visible or slot.candidate is not None:
            return [ReplayRejected(slot.question.id)]
        reading_ms = self._rules.reading_ms(slot.question.text)
        slot.replay_used = True
        slot.visible = True
        slot.visible_since_ms = now_ms
        slot.reading_end_ms = now_ms + reading_ms
        slot.pauses.append([now_ms, now_ms + reading_ms])
        return [self._show_action(slot.question)]

    def tick(self, now_ms: int, pending_finals: int) -> list[Action]:
        slot = self._current
        if slot is None:
            return []
        actions: list[Action] = []
        if slot.visible and now_ms >= slot.reading_end_ms:
            slot.visible = False
            actions.append(HideQuestion(slot.question.id))
        elif slot.visible and slot.hide_deferred and now_ms >= self._replay_min_end(slot):
            slot.visible = False
            actions.append(HideQuestion(slot.question.id))
            # The question was on screen until the minimum ended, not until this tick.
            for window in slot.pauses:
                if window[0] <= self._replay_min_end(slot) < window[1]:
                    window[1] = self._replay_min_end(slot)
        if slot.candidate is None:
            reason = self._detect_reason(slot, now_ms)
            if reason is not None:
                slot.candidate = (reason, now_ms)
        if slot.candidate is not None:
            reason, decided_ms = slot.candidate
            waited = now_ms - decided_ms
            if pending_finals <= 0 or waited >= self._rules.final_wait_cap_ms:
                actions += self._advance(slot, reason, now_ms)
        return actions

    def add_questions(self, questions: list[PlannedQuestion], now_ms: int) -> list[Action]:
        """Queue more questions (round 2). Shows the first one if the round was finished."""
        if self._stopped:
            return []
        self._queue.extend(questions)
        if self._current is not None:
            return []
        return self._show_next(now_ms) or [RoundFinished(self._last_round + 1)]

    def stop(self, now_ms: int) -> list[Action]:
        """End the interview; the current question (if any) ends with reason "stopped"."""
        slot = self._current
        self._stopped = True
        self._queue.clear()
        if slot is None:
            return []
        actions: list[Action] = []
        if slot.visible:
            slot.visible = False
            actions.append(HideQuestion(slot.question.id))
        self._finish(slot, "stopped", now_ms)
        actions.append(Advanced(slot.question.id, "stopped"))
        return actions

    def items(self) -> list[ItemRecord]:
        """Records of finished questions (a question in progress is not included)."""
        records = []
        for slot in self._slots:
            if slot.ended_ms is None or slot.reason is None:
                continue
            utterances = sorted(slot.utterances, key=lambda u: u.start_ms)
            records.append(
                ItemRecord(
                    question=slot.question,
                    shown_ms=slot.shown_ms,
                    answer_started_ms=slot.answer_started_ms,
                    ended_ms=slot.ended_ms,
                    advance_reason=slot.reason,
                    replay_used=slot.replay_used,
                    utterances=utterances,
                    transcript=" ".join(u.text for u in utterances),
                )
            )
        return records

    # -- internals --------------------------------------------------------------

    def _show_action(self, question: PlannedQuestion) -> ShowQuestion:
        return ShowQuestion(
            question.id,
            question.text,
            self._rules.reading_ms(question.text),
            self._rules.answer_limit_for(question),
        )

    def _show_next(self, now_ms: int) -> list[Action]:
        if self._stopped or not self._queue:
            return []
        question = self._queue.pop(0)
        reading_end = now_ms + self._rules.reading_ms(question.text)
        slot = _Slot(question, now_ms, reading_end, reading_end, visible_since_ms=now_ms)
        self._slots.append(slot)
        self._current = slot
        self._last_round = question.round
        return [self._show_action(question)]

    def _replay_min_end(self, slot: _Slot) -> int:
        return slot.visible_since_ms + self._rules.replay_min_visible_ms

    def _track_run(self, start_ms: int, end_ms: int) -> None:
        gap_limit = self._rules.endpoint_ms
        if self._run_end_ms is None or start_ms - self._run_end_ms >= gap_limit:
            self._run_start_ms = start_ms
        self._run_end_ms = max(self._run_end_ms or 0, end_ms)

    def _is_carry_over(self, slot: _Slot, start_ms: int) -> bool:
        """Speech still running from before the question appeared (e.g. past the final-wait
        cap) must not hide the new question or count as its answer. Bounded so that endless
        noise cannot hide a question forever."""
        return (
            self._run_start_ms is not None
            and self._run_start_ms < slot.shown_ms
            and start_ms < slot.shown_ms + self._rules.max_utterance_ms
        )

    def _detect_reason(self, slot: _Slot, now_ms: int) -> AdvanceReason | None:
        rules = self._rules
        now = slot.eff(now_ms)
        if slot.answer_started_ms is None:
            if now - slot.eff(slot.first_reading_end_ms) >= rules.no_response_ms:
                return "no_response"
            return None
        answer_ms = now - slot.eff(slot.answer_started_ms)
        last_voiced = slot.last_voiced_end_ms if slot.last_voiced_end_ms is not None else 0
        limit = rules.answer_limit_for(slot.question)
        # Normally wait for the utterance to end; continuous voice (noise) is cut after one
        # more maximum-length utterance.
        if answer_ms >= limit and (
            now_ms >= last_voiced + rules.endpoint_ms or answer_ms >= limit + rules.max_utterance_ms
        ):
            return "time_limit"
        if answer_ms >= rules.min_answer_ms and now - slot.eff(last_voiced) >= rules.silence_ms:
            return "silence"
        return None

    def _finish(self, slot: _Slot, reason: AdvanceReason, now_ms: int) -> None:
        slot.ended_ms = now_ms
        slot.reason = reason
        self._current = None

    def _advance(self, slot: _Slot, reason: AdvanceReason, now_ms: int) -> list[Action]:
        actions: list[Action] = []
        if slot.visible:
            slot.visible = False
            actions.append(HideQuestion(slot.question.id))
        self._finish(slot, reason, now_ms)
        actions.append(Advanced(slot.question.id, reason))
        actions += self._show_next(now_ms) or [RoundFinished(slot.question.round)]
        return actions
