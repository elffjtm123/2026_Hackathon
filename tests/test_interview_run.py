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
