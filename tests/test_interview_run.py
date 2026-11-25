"""Seam: InterviewRun (conductor + pipeline glue). Fake clock, emit sink and pending count.

The loop's own tick interval is made huge so tests drive time explicitly with `step()`;
frame-triggered wake-ups are still exercised through the running loop.
"""

import asyncio
from dataclasses import dataclass, field

import pytest

from app.modules.interview.composition import TurnRules
from app.modules.interview.questions import FinalUtterance, ItemRecord, PlannedQuestion
from app.realtime.interview_run import InterviewRun

# 10 characters -> 2000 + 1000 = 3000 ms of reading time.
RULES = TurnRules(reading_base_ms=2000, reading_chars_per_second=10, stall_allowance_ms=0)
# The default stall allowance (1.5 s), for the tests of the audio-timeline clock.
LAG_RULES = TurnRules(reading_base_ms=2000, reading_chars_per_second=10)
TEXT = "가나다라마바사아자차"


def question(qid: str, round_: int = 1) -> PlannedQuestion:
    return PlannedQuestion(id=qid, kind="common", subtype="x", text=TEXT, round=round_)  # type: ignore[arg-type]


@dataclass
class Harness:
    now: int = 0
    pending: int = 0
    events: list[tuple[str, dict]] = field(default_factory=list)
    saved: list[list[ItemRecord]] = field(default_factory=list)

    def run(self, *ids: str, rules: TurnRules = RULES) -> InterviewRun:
        async def emit(name: str, data: dict) -> None:
            self.events.append((name, data))

        return InterviewRun(
            [question(i) for i in ids],
            rules,
            clock=lambda: self.now,
            emit=emit,
            pending_finals=lambda: self.pending,
            save_items=self.saved.append,
            tick_seconds=3600,
        )

    def names(self) -> list[str]:
        return [name for name, _ in self.events]

    def last(self, name: str) -> dict:
        return next(data for n, data in reversed(self.events) if n == name)


def utterance(start: int, end: int, text: str = "안녕하세요") -> FinalUtterance:
    return FinalUtterance("u1", start, end, text, end - start)


@pytest.mark.asyncio
async def test_start_shows_the_first_question_with_its_timing() -> None:
    h = Harness()
    run = h.run("q1", "q2")
    await run.start()
    try:
        assert h.events == [
            (
                "interview.question",
                {
                    "question_id": "q1",
                    "round": 1,
                    "index": 1,
                    "total": 2,
                    "text": TEXT,
                    "reading_ms": 3000,
                    "answer_limit_ms": 120000,
                    "replay_available": True,
                },
            )
        ]
    finally:
        await run.stop()


@pytest.mark.asyncio
async def test_a_full_interview_hides_advances_and_finishes() -> None:
    h = Harness()
    run = h.run("q1", "q2")
    await run.start()
    try:
        h.now = 500
        run.observe_frame(500, 520, True)  # first voiced frame hides the question at once
        await asyncio.sleep(0.01)  # the loop is woken by the frame, no tick needed
        assert h.names() == ["interview.question", "interview.question_hidden"]
        assert h.last("interview.question_hidden") == {"question_id": "q1"}

        h.now = 1500
        run.observe_frame(1480, 1500, True)
        run.on_final(utterance(300, 1500))
        h.now = 11_600  # 10 s of answer and 4 s of silence: a candidate, but a final is pending
        h.pending = 1
        await run.step()
        assert "interview.advanced" not in h.names()

        h.now, h.pending = 11_700, 0
        await run.step()
        assert h.last("interview.advanced") == {"question_id": "q1", "reason": "silence"}
        second = h.last("interview.question")
        assert (second["question_id"], second["index"], second["total"]) == ("q2", 2, 2)

        h.now = 29_700  # 15 s after q2's reading time: no response
        await run.step()
        assert h.last("interview.advanced") == {"question_id": "q2", "reason": "no_response"}
        assert h.names()[-1] == "interview.finished"
        assert h.events[-1][1] == {}

        await run.stop()
        run.finalize()
        items = h.saved[-1]
        assert [i.question.id for i in items] == ["q1", "q2"]
        assert items[0].transcript == "안녕하세요" and items[0].advance_reason == "silence"
        assert items[1].advance_reason == "no_response" and items[1].answer_started_ms is None
    finally:
        await run.stop()


@pytest.mark.asyncio
async def test_pending_finals_delay_the_advance_until_the_wait_cap() -> None:
    h = Harness()
    run = h.run("q1", "q2")
    await run.start()
    try:
        h.now = 18_000  # 15 s of silence after the 3 s reading time: no_response candidate
        h.pending = 2
        await run.step()
        h.now = 20_000
        await run.step()
        assert "interview.advanced" not in h.names()
        h.now = 21_000  # 3 s cap since the decision
        await run.step()
        assert h.last("interview.advanced")["reason"] == "no_response"
    finally:
        await run.stop()


@pytest.mark.asyncio
async def test_replay_is_accepted_once_then_rejected() -> None:
    h = Harness()
    run = h.run("q1")
    await run.start()
    try:
        h.now = 3000
        await run.step()  # reading time over: hidden
        h.now = 3100
        await run.replay("q1")
        shown = h.last("interview.question")
        assert shown["question_id"] == "q1" and shown["replay_available"] is False
        assert h.names().count("interview.question") == 2
        h.now = 6200
        await run.step()  # replay reading over: hidden again
        await run.replay("q1")
        assert h.last("interview.replay_rejected") == {"question_id": "q1"}
        assert h.names().count("interview.question") == 2
    finally:
        await run.stop()


@pytest.mark.asyncio
async def test_replay_of_a_question_that_is_not_current_is_rejected() -> None:
    h = Harness()
    run = h.run("q1", "q2")
    await run.start()
    try:
        h.now = 3000
        await run.step()
        await run.replay("q2")  # not shown yet
        await run.replay("nope")
        assert [d for n, d in h.events if n == "interview.replay_rejected"] == [
            {"question_id": "q2"},
            {"question_id": "nope"},
        ]
        assert h.names().count("interview.question") == 1
    finally:
        await run.stop()


@pytest.mark.asyncio
async def test_stop_mid_question_saves_the_item_as_stopped() -> None:
    h = Harness()
    run = h.run("q1", "q2")
    await run.start()
    h.now = 600
    run.observe_frame(600, 620, True)
    run.on_final(utterance(400, 1000, "중간 답변"))
    h.now = 2000
    await run.stop()
    assert h.last("interview.advanced") == {"question_id": "q1", "reason": "stopped"}
    assert "interview.finished" not in h.names()
    assert "q2" not in [d.get("question_id") for _, d in h.events]
    run.finalize()
    (item,) = h.saved[-1]
    assert item.advance_reason == "stopped" and item.transcript == "중간 답변"
    assert (item.shown_ms, item.answer_started_ms, item.ended_ms) == (0, 600, 2000)


@pytest.mark.asyncio
async def test_a_late_final_after_stop_still_reaches_the_saved_items() -> None:
    h = Harness()
    run = h.run("q1")
    await run.start()
    h.now = 600
    run.observe_frame(600, 620, True)
    h.now = 2000
    await run.stop()
    run.on_final(utterance(400, 1900, "늦게 도착"))  # drained while the pipeline stops
    items = run.finalize()
    assert items[0]["transcript"] == "늦게 도착"
    assert h.saved[-1][0].transcript == "늦게 도착"


@pytest.mark.asyncio
async def test_finalize_serializes_items_for_the_report_and_is_repeatable() -> None:
    h = Harness()
    run = h.run("q1")
    await run.start()
    h.now = 600
    run.observe_frame(600, 620, True)
    run.on_final(utterance(400, 1000, "답변"))
    h.now = 2000
    await run.stop()
    assert run.finalize() == [
        {
            "question_id": "q1",
            "round": 1,
            "parent_id": None,
            "text": TEXT,
            "shown_ms": 0,
            "answer_started_ms": 600,
            "ended_ms": 2000,
            "advance_reason": "stopped",
            "replay_used": False,
            "transcript": "답변",
            "utterances": [
                {
                    "utterance_id": "u1",
                    "start_ms": 400,
                    "end_ms": 1000,
                    "text": "답변",
                    "voiced_ms": 600,
                }
            ],
        }
    ]
    assert run.finalize() == run.finalize()


@pytest.mark.asyncio
async def test_finalize_without_stop_ends_the_current_question_as_stopped() -> None:
    h = Harness()
    run = h.run("q1")
    await run.start()
    try:
        h.now = 700
        items = run.finalize()
        assert items[0]["advance_reason"] == "stopped" and items[0]["ended_ms"] == 700
    finally:
        await run.stop()


@pytest.mark.asyncio
async def test_a_failing_store_does_not_break_finalize() -> None:
    h = Harness()

    def broken(_: list[ItemRecord]) -> None:
        raise RuntimeError("store gone")

    run = h.run("q1")
    run._save_items = broken  # type: ignore[attr-defined]
    await run.start()
    await run.stop()
    assert run.finalize()[0]["advance_reason"] == "stopped"


@pytest.mark.asyncio
async def test_the_tick_task_ends_with_stop_and_stop_is_repeatable() -> None:
    h = Harness()
    run = h.run("q1")
    assert not run.running
    await run.start()
    assert run.running
    await run.stop()
    assert not run.running
    await run.stop()
    before = len(h.events)
    run.observe_frame(100, 120, True)  # after stop: ignored
    await asyncio.sleep(0.01)
    assert len(h.events) == before


@pytest.mark.asyncio
async def test_stop_cancels_a_loop_that_is_blocked_emitting() -> None:
    h = Harness()
    gate = asyncio.Event()
    emitted = 0

    async def slow_emit(name: str, data: dict) -> None:
        nonlocal emitted
        emitted += 1
        if emitted > 1:
            await gate.wait()  # never released

    run = InterviewRun(
        [question("q1")],
        RULES,
        clock=lambda: h.now,
        emit=slow_emit,
        pending_finals=lambda: 0,
        save_items=h.saved.append,
        tick_seconds=3600,
    )
    run.stop_flush_seconds = 0.05  # the final flush to a stuck subscriber is bounded too
    await run.start()
    h.now = 600
    run.observe_frame(600, 620, True)  # the hide blocks inside emit
    await asyncio.sleep(0.01)
    await asyncio.wait_for(run.stop(), 2)
    assert not run.running


@pytest.mark.asyncio
async def test_a_conductor_bug_is_contained_and_stop_still_works() -> None:
    h = Harness()
    run = h.run("q1")

    def boom(_: int, __: int, ___: bool) -> list:
        raise RuntimeError("conductor bug")

    await run.start()
    run._conductor.on_frame = boom  # type: ignore[attr-defined, method-assign]
    run.observe_frame(100, 120, True)  # a conductor bug must not reach the audio worker
    run.observe_frame(140, 160, True)
    await run.stop()
    assert not run.running
    assert run.finalize()[0]["advance_reason"] == "stopped"


@pytest.mark.asyncio
async def test_round_one_finish_is_a_seam_for_round_two() -> None:
    h = Harness()
    seen: list[int] = []

    class Round(InterviewRun):
        async def _on_round_finished(self, round_: int) -> None:
            seen.append(round_)
            await super()._on_round_finished(round_)

    async def emit(name: str, data: dict) -> None:
        h.events.append((name, data))

    run = Round(
        [question("q1")],
        RULES,
        clock=lambda: h.now,
        emit=emit,
        pending_finals=lambda: 0,
        save_items=h.saved.append,
        tick_seconds=3600,
    )
    await run.start()
    try:
        h.now = 18_000
        await run.step()
        assert seen == [1]
        assert h.names()[-1] == "interview.finished"
    finally:
        await run.stop()


# --- the conductor runs on the audio timeline, not the wall clock ---


class Lagging:
    """Frames reach the run `lag` ms after the audio they cover; the wall clock keeps going."""

    def __init__(self, h: Harness, run: InterviewRun, lag: int) -> None:
        self.h, self.run, self.lag, self.next_chunk = h, run, lag, 200

    async def advance_to(self, wall: int, speech: tuple[int, int] | None) -> None:
        while self.next_chunk + self.lag <= wall:
            for f in range(self.next_chunk - 200, self.next_chunk, 20):
                voiced = speech is not None and speech[0] <= f < speech[1]
                self.run.observe_frame(f, f + 20, voiced)
            self.next_chunk += 200
        self.h.now = wall
        await self.run.step()


@pytest.mark.parametrize("lag", [0, 300, 1000])
@pytest.mark.asyncio
async def test_lagging_frames_never_cut_continuous_speech_past_the_answer_limit(lag: int) -> None:
    h = Harness()
    run = h.run("q1", "q2", rules=LAG_RULES)
    await run.start(0)
    feeder = Lagging(h, run, lag)
    speech_end = 130_000  # limit is 120 s after the answer began at 5 s: cut only at its end
    advanced_at = None
    try:
        for wall in range(0, 140_000, 200):
            await feeder.advance_to(wall, (5000, speech_end))
            if "interview.advanced" in h.names():
                reason = h.last("interview.advanced")["reason"]
                advanced_at = wall
                break
    finally:
        await run.stop()
    assert reason == "time_limit"
    assert advanced_at is not None and advanced_at - lag >= speech_end  # after the utterance ended


@pytest.mark.asyncio
async def test_silence_is_measured_on_the_audio_timeline_with_lagging_frames() -> None:
    h = Harness()
    run = h.run("q1", "q2", rules=LAG_RULES)
    await run.start(0)
    feeder = Lagging(h, run, 1000)
    try:
        for wall in range(0, 20_000, 200):
            await feeder.advance_to(wall, (500, 2000))
            if "interview.advanced" in h.names():
                reason = h.last("interview.advanced")["reason"]
                break
    finally:
        await run.stop()
    # 4 s of silence after 2 s of speech, and 1 s of lag: not before 6 s of wall time + lag.
    assert reason == "silence"
    assert wall - 1000 >= 2000 + 4000 - 200


@pytest.mark.asyncio
async def test_a_question_still_advances_when_audio_stops_completely() -> None:
    h = Harness()
    run = h.run("q1", "q2", rules=LAG_RULES)
    await run.start(0)
    advanced_at = None
    try:
        for wall in range(0, 30_000, 200):
            h.now = wall
            if wall < 2000:  # speech, then no frame at all (the microphone went away)
                run.observe_frame(wall, wall + 20, True)
            await run.step()
            if "interview.advanced" in h.names():
                reason = h.last("interview.advanced")["reason"]
                advanced_at = wall
                break
    finally:
        await run.stop()
    assert reason == "silence"
    # silence needs 10 s of answer time and 4 s quiet; the stall allowance adds 1.5 s at most.
    assert advanced_at is not None and advanced_at <= 10_500 + 1500 + 400


@pytest.mark.asyncio
async def test_no_response_still_advances_without_any_audio() -> None:
    h = Harness()
    run = h.run("q1", "q2", rules=LAG_RULES)
    await run.start(0)
    advanced_at = None
    try:
        for wall in range(0, 30_000, 200):
            h.now = wall
            await run.step()
            if "interview.advanced" in h.names():
                reason = h.last("interview.advanced")["reason"]
                advanced_at = wall
                break
    finally:
        await run.stop()
    assert reason == "no_response"
    assert advanced_at is not None and 18_000 <= advanced_at <= 18_000 + 1500 + 400


@pytest.mark.asyncio
async def test_the_run_clock_never_goes_backwards() -> None:
    h = Harness()
    run = h.run("q1", rules=LAG_RULES)
    await run.start(0)
    try:
        run.observe_frame(8000, 8020, False)  # audio far ahead of the wall clock
        h.now = 100
        await run.step()
        run.observe_frame(1000, 1020, False)  # an older frame must not rewind anything
        await run.step()
        await run.stop()
    finally:
        await run.stop()
    run.finalize()
    assert h.saved[-1][0].ended_ms >= 8020


# --- review fixes: start robustness, finalize cancels the task, started flag ---


@pytest.mark.asyncio
async def test_start_takes_the_audio_origin_as_the_question_time() -> None:
    h = Harness(now=5000)
    run = h.run("q1")
    await run.start(4000)
    try:
        run.observe_frame(4000, 4020, True)  # the first frame of the session is not "before" it
        await run.step()
        assert h.names()[-1] == "interview.question_hidden"
    finally:
        await run.stop()


@pytest.mark.asyncio
async def test_a_conductor_error_in_start_does_not_escape() -> None:
    h = Harness()
    run = h.run("q1")

    def boom(_: int) -> list:
        raise RuntimeError("conductor bug")

    run._conductor.start = boom  # type: ignore[method-assign]
    await run.start(0)
    assert run.started and not run.running
    await run.stop()


@pytest.mark.asyncio
async def test_finalize_without_stop_ends_the_tick_task() -> None:
    h = Harness()
    run = h.run("q1")
    assert not run.started
    await run.start(0)
    assert run.started
    run.finalize()
    await asyncio.sleep(0.01)
    assert not run.running
    assert not [t for t in asyncio.all_tasks() if t.get_name() == "interview-run"]


@pytest.mark.asyncio
async def test_excessive_frame_lag_is_logged_once_without_content(caplog) -> None:
    h = Harness()
    run = h.run("q1", rules=LAG_RULES)
    await run.start(0)
    try:
        with caplog.at_level("WARNING", logger="app.realtime.interview_run"):
            for wall in range(0, 6000, 200):
                h.now = wall
                run.observe_frame(wall - 3000, wall - 2980, True)  # frames 3 s behind the wall
                await run.step()
        records = [
            r for r in caplog.records if r.message == "interview_frame_lag_exceeds_allowance"
        ]
        assert len(records) == 1
        assert records[0].lag_ms > LAG_RULES.stall_allowance_ms
    finally:
        await run.stop()


# --- round break: follow-up questions between the two rounds ---

from app.modules.interview.questions import RubricItem  # noqa: E402
from app.realtime.interview_run import RoundBreak  # noqa: E402

LONG = "저는 검출 모델을 학습시키고 서버에 올려서 성능을 확인했고 결과가 좋았습니다"


def scored(qid: str) -> PlannedQuestion:
    return PlannedQuestion(
        id=qid,
        kind="common",
        subtype="x",
        text=TEXT,
        rubric_items=[RubricItem.SPECIFICITY],
    )


def follow_up(parent: str = "q1") -> PlannedQuestion:
    return PlannedQuestion(
        id=f"{parent}-f",
        kind="follow_up",
        subtype="own_role",
        text=TEXT,
        rubric_items=[RubricItem.SPECIFICITY],
        parent_id=parent,
        round=2,
    )


class Hooks:
    """Recording round-break hooks; each step can be made to fail or to block."""

    def __init__(self, h: Harness, questions: list[PlannedQuestion] | None = None) -> None:
        self.h = h
        self.questions = [follow_up()] if questions is None else questions
        self.calls: list[str] = []
        self.items: list[ItemRecord] = []
        self.fail: dict[str, BaseException] = {}
        self.block: dict[str, asyncio.Event] = {}
        self.cancelled: list[str] = []
        self.at_resume = 0

    async def step(self, name: str) -> None:
        self.calls.append(name)
        self.h.events.append((f"hook.{name}", {}))  # ordering against the events
        try:
            if name in self.block:
                await self.block[name].wait()
        except asyncio.CancelledError:
            self.cancelled.append(name)
            raise
        if name in self.fail:
            raise self.fail[name]

    async def suspend(self) -> None:
        await self.step("suspend")

    async def resume(self) -> None:
        self.at_resume = self.h.now
        await self.step("resume")

    async def generate(self, items: list[ItemRecord]) -> list[PlannedQuestion]:
        self.items = items
        await self.step("follow_ups")
        return self.questions

    def hooks(self, timeout: float = 5) -> RoundBreak:
        return RoundBreak(self.suspend, self.resume, self.generate, timeout_seconds=timeout)


def break_run(
    h: Harness, hooks: RoundBreak | None, *ids: str, rules: TurnRules = RULES
) -> InterviewRun:
    async def emit(name: str, data: dict) -> None:
        h.events.append((name, data))

    return InterviewRun(
        [scored(i) for i in ids],
        rules,
        clock=lambda: h.now,
        emit=emit,
        pending_finals=lambda: h.pending,
        save_items=h.saved.append,
        tick_seconds=3600,
        round_break=hooks,
    )


async def answer(h: Harness, run: InterviewRun, shown: int, text: str = LONG) -> None:
    """Speak from shown+500 to shown+11 s, then let silence end the question."""
    h.now = shown + 500
    run.observe_frame(shown + 500, shown + 520, True)
    run.on_final(utterance(shown + 300, shown + 11_000, text))
    run.observe_frame(shown + 10_980, shown + 11_000, True)
    h.now = shown + 15_100
    await run.step()


async def until(predicate, timeout: float = 2.0) -> None:
    for _ in range(int(timeout / 0.005)):
        if predicate():
            return
        await asyncio.sleep(0.005)
    raise AssertionError("condition not reached")


def stages(h: Harness) -> list[str]:
    return [d["stage"] for n, d in h.events if n == "interview.round_break"]


@pytest.mark.asyncio
async def test_a_round_break_generates_follow_ups_and_runs_round_two() -> None:
    h = Harness()
    fake = Hooks(h)
    fake.block["follow_ups"] = release = asyncio.Event()
    run = break_run(h, fake.hooks(), "q1")
    await run.start(0)
    try:
        await answer(h, run, 0)
        await until(lambda: fake.calls == ["suspend", "follow_ups"])
        assert "interview.finished" not in h.names()  # round 1 is not the end
        h.now = 60_000  # the break takes a minute
        release.set()
        await until(lambda: h.names().count("interview.question") == 2)
        names = h.names()
        assert names[names.index("interview.advanced") :] == [
            "interview.advanced",
            "interview.round_break",
            "hook.suspend",
            "interview.round_break",
            "hook.follow_ups",
            "interview.round_break",
            "hook.resume",
            "interview.question",
        ]
        rounds = [d for n, d in h.events if n == "interview.round_break"]
        assert rounds == [
            {"stage": "suspending"},
            {"stage": "generating"},
            {"stage": "resuming", "follow_up_count": 1},
        ]
        assert [i.question.id for i in fake.items] == ["q1"]
        second = h.last("interview.question")
        assert (second["question_id"], second["round"], second["index"], second["total"]) == (
            "q1-f",
            2,
            1,
            1,
        )
        # Round 2 starts when the models are back, not when round 1 ended: the break does not
        # count as answer or no-response time.
        h.now = 60_000 + 14_000
        await run.step()
        assert "q1-f" not in [
            d.get("question_id") for n, d in h.events if n == "interview.advanced"
        ]
        await answer(h, run, 60_000)
        assert h.last("interview.advanced") == {"question_id": "q1-f", "reason": "silence"}
        assert h.names()[-1] == "interview.finished" and h.names().count("interview.finished") == 1
        await run.stop()
        run.finalize()
        first, child = h.saved[-1]
        assert (first.question.id, child.question.id) == ("q1", "q1-f")
        assert child.question.parent_id == "q1" and child.shown_ms == 60_000
    finally:
        await run.stop()


@pytest.mark.asyncio
async def test_without_evaluable_answers_the_break_is_skipped_before_anything_is_stopped() -> None:
    h = Harness()
    fake = Hooks(h)
    run = break_run(h, fake.hooks(), "q1")
    await run.start(0)
    try:
        h.now = 18_000  # no response
        await run.step()
        await until(lambda: "interview.finished" in h.names())
        assert fake.calls == []  # the realtime models were never touched
        assert [d for n, d in h.events if n == "interview.round_break"] == [
            {"stage": "skipped", "follow_up_count": 0}
        ]
        assert h.names()[-2:] == ["interview.round_break", "interview.finished"]
    finally:
        await run.stop()


@pytest.mark.asyncio
async def test_a_short_answer_alone_is_not_worth_a_break() -> None:
    h = Harness()
    fake = Hooks(h)
    run = break_run(h, fake.hooks(), "q1")
    await run.start(0)
    try:
        await answer(h, run, 0, text="네 그렇습니다")  # under 20 syllables
        await until(lambda: "interview.finished" in h.names())
        assert fake.calls == [] and stages(h) == ["skipped"]
    finally:
        await run.stop()


@pytest.mark.parametrize(
    "failure",
    ["none", "error", "timeout"],
    ids=["no_follow_ups", "generation_fails", "generation_times_out"],
)
@pytest.mark.asyncio
async def test_no_follow_ups_ends_the_interview_without_restarting_the_models(failure) -> None:
    h = Harness()
    fake = Hooks(h, [] if failure == "none" else None)
    if failure == "error":
        fake.fail["follow_ups"] = ValueError("model failed")
    if failure == "timeout":
        fake.block["follow_ups"] = asyncio.Event()  # never released
    run = break_run(h, fake.hooks(timeout=0.05), "q1")
    await run.start(0)
    try:
        await answer(h, run, 0)
        await until(lambda: "interview.finished" in h.names())
        assert fake.calls == ["suspend", "follow_ups"]  # no resume just to finish
        assert stages(h) == ["suspending", "generating", "skipped"]
        assert h.last("interview.round_break") == {"stage": "skipped", "follow_up_count": 0}
        assert h.names()[-2:] == ["interview.round_break", "interview.finished"]
        assert fake.cancelled == (["follow_ups"] if failure == "timeout" else [])
        assert h.names().count("interview.question") == 1
    finally:
        await run.stop()


@pytest.mark.parametrize("step", ["suspend", "resume"])
@pytest.mark.asyncio
async def test_a_failing_suspend_or_resume_reports_an_error_and_finishes(step) -> None:
    h = Harness()
    fake = Hooks(h)
    fake.fail[step] = ValueError("MODEL_UNAVAILABLE_OR_BUSY")
    run = break_run(h, fake.hooks(), "q1")
    await run.start(0)
    try:
        await answer(h, run, 0)
        await until(lambda: "interview.finished" in h.names())
        error = h.last("error")
        assert error["code"] == "INTERVIEW_ROUND_BREAK_FAILED"
        assert h.names()[-2:] == ["error", "interview.finished"]
        assert "follow_ups" in fake.calls if step == "resume" else "follow_ups" not in fake.calls
        assert h.names().count("interview.question") == 1
    finally:
        await run.stop()


@pytest.mark.parametrize("blocked", ["suspend", "follow_ups", "resume"])
@pytest.mark.asyncio
async def test_stopping_during_the_break_cancels_it_and_keeps_the_items(blocked) -> None:
    h = Harness()
    fake = Hooks(h)
    fake.block[blocked] = asyncio.Event()  # never released
    run = break_run(h, fake.hooks(), "q1")
    await run.start(0)
    await answer(h, run, 0)
    await until(lambda: blocked in fake.calls)
    before = list(h.names())
    await asyncio.wait_for(run.stop(), 2)
    assert fake.cancelled == [blocked]
    assert "interview.finished" not in h.names()
    assert h.names() == before  # nothing more is said after the stop
    run.finalize()
    (item,) = h.saved[-1]
    assert item.question.id == "q1" and item.advance_reason == "silence"
    assert h.names().count("interview.question") == 1


@pytest.mark.asyncio
async def test_finalize_without_stop_also_cancels_a_break_in_progress() -> None:
    h = Harness()
    fake = Hooks(h)
    fake.block["follow_ups"] = asyncio.Event()
    run = break_run(h, fake.hooks(), "q1")
    await run.start(0)
    await answer(h, run, 0)
    await until(lambda: "follow_ups" in fake.calls)
    run.finalize()
    await until(lambda: fake.cancelled == ["follow_ups"])
    assert not [t for t in asyncio.all_tasks() if t.get_name() == "interview-round-break"]


@pytest.mark.asyncio
async def test_a_run_without_break_hooks_finishes_after_round_one() -> None:
    h = Harness()
    run = break_run(h, None, "q1")
    await run.start(0)
    try:
        await answer(h, run, 0)
        assert h.names()[-1] == "interview.finished"
        assert "interview.round_break" not in h.names()
    finally:
        await run.stop()


@pytest.mark.asyncio
async def test_follow_ups_are_numbered_within_round_two() -> None:
    h = Harness()
    two = [follow_up("q1"), follow_up("q2")]
    fake = Hooks(h, two)
    run = break_run(h, fake.hooks(), "q1", "q2")
    await run.start(0)
    try:
        await answer(h, run, 0)
        await answer(h, run, h.now)  # q2 was shown when q1 advanced
        await until(lambda: h.names().count("interview.question") == 3)
        await answer(h, run, h.now)  # q1-f is shown when the models are back
        await answer(h, run, h.now)
        shown = [d for n, d in h.events if n == "interview.question" and d["round"] == 2]
        assert [(d["question_id"], d["index"], d["total"]) for d in shown] == [
            ("q1-f", 1, 2),
            ("q2-f", 2, 2),
        ]
        assert h.names().count("interview.finished") == 1
    finally:
        await run.stop()


@pytest.mark.asyncio
async def test_a_final_drained_by_the_suspend_reaches_the_follow_ups() -> None:
    h = Harness()
    fake = Hooks(h)
    run = break_run(h, fake.hooks(), "q1")
    await run.start(0)
    plain_suspend = fake.suspend

    async def suspend() -> None:
        # The pipeline's drain delivers the last answer's final while it suspends.
        run.on_final(utterance(300, 11_000, LONG))
        await plain_suspend()

    run._round_break.suspend = suspend  # type: ignore[union-attr]
    try:
        h.now = 500
        run.observe_frame(500, 520, True)
        run.observe_frame(10_980, 11_000, True)
        h.pending = 1  # the final is still being transcribed
        h.now = 15_100
        await run.step()
        h.now = 15_100 + 3_100  # the final wait cap passes: the question advances without it
        await run.step()
        await until(lambda: "follow_ups" in fake.calls)
        assert [i.transcript for i in fake.items] == [LONG]
    finally:
        await run.stop()


@pytest.mark.asyncio
async def test_the_last_question_of_round_one_is_seen_with_its_drained_final() -> None:
    h = Harness()
    fake = Hooks(h)
    run = break_run(h, fake.hooks(), "q1", "q2")
    await run.start(0)
    plain_suspend = fake.suspend
    try:
        await answer(h, run, 0)
        shown = h.now

        async def suspend() -> None:
            run.on_final(utterance(shown + 300, shown + 11_000, LONG))
            await plain_suspend()

        run._round_break.suspend = suspend  # type: ignore[union-attr]
        h.now = shown + 500
        run.observe_frame(shown + 500, shown + 520, True)
        run.observe_frame(shown + 10_980, shown + 11_000, True)
        h.pending = 1
        h.now = shown + 15_100
        await run.step()
        h.now = shown + 18_200
        await run.step()
        await until(lambda: "follow_ups" in fake.calls)
        assert [i.question.id for i in fake.items] == ["q1", "q2"]
        assert all(i.transcript for i in fake.items)
    finally:
        await run.stop()


@pytest.mark.asyncio
async def test_a_break_found_pointless_only_after_the_suspend_is_skipped_without_resume() -> None:
    h = Harness()
    fake = Hooks(h)
    run = break_run(h, fake.hooks(), "q1")
    await run.start(0)
    try:
        h.now = 500
        run.observe_frame(500, 520, True)
        h.pending = 1  # a final may still come, so the models are stopped to find out
        h.now = 15_100
        await run.step()
        h.now = 18_200
        await run.step()
        await until(lambda: "interview.finished" in h.names())
        assert fake.calls == ["suspend"] and stages(h) == ["suspending", "skipped"]
    finally:
        await run.stop()


@pytest.mark.asyncio
async def test_round_two_starts_on_the_wall_clock_after_the_break() -> None:
    h = Harness()
    fake = Hooks(h)
    fake.block["follow_ups"] = release = asyncio.Event()
    run = break_run(h, fake.hooks(), "q1", rules=LAG_RULES)  # stall allowance 1.5 s
    await run.start(0)
    try:
        await answer(h, run, 0)
        h.now += 2000  # the allowance holds the conductor's clock back
        await run.step()
        await until(lambda: "follow_ups" in fake.calls)
        h.now = 60_000
        release.set()
        await until(lambda: h.names().count("interview.question") == 2)
        await run.stop()
        run.finalize()
        # Not 58 500 (wall minus the allowance) and not the 15 000 where round 1 ended.
        assert h.saved[-1][1].shown_ms == 60_000
    finally:
        await run.stop()
