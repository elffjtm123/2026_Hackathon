"""Seam: SessionPipeline's interview hooks (frames, finals, pending count, start, stop, report)."""

import asyncio

import pytest

from app.ai.base import MediaPayload
from app.modules.interview.questions import FinalUtterance
from tests.test_delivery_pipeline import (  # noqa: F401  (vad is a fixture, used by name below)
    LOUD,
    QUIET,
    Talker,
    delivery_pipeline,
    feed,
    start_at,
    vad,
    voiced_then_silence,
)

pytestmark = pytest.mark.usefixtures("vad")


class Recorder:
    """Stands in for an InterviewRun: records what the pipeline hands over."""

    def __init__(self) -> None:
        self.frames: list[tuple[int, int, bool]] = []
        self.finals: list[FinalUtterance] = []
        self.calls: list[str] = []

    started = False

    async def start(self, origin_ms: int | None = None) -> None:
        self.started = True
        self.calls.append("start")
        self.origin = origin_ms

    async def stop(self) -> None:
        self.calls.append("stop")

    def finalize(self) -> list[dict]:
        self.calls.append("finalize")
        return [{"question_id": "q1"}]

    def observe_frame(self, start_ms: int, end_ms: int, voiced: bool) -> None:
        self.frames.append((start_ms, end_ms, voiced))

    def on_final(self, utterance: FinalUtterance) -> None:
        self.finals.append(utterance)


@pytest.mark.asyncio
async def test_frames_and_finals_arrive_on_the_session_clock() -> None:
    p = delivery_pipeline(Talker("안녕하세요"))
    p.interview = recorder = Recorder()
    origin = await start_at(p)
    await feed(p, voiced_then_silence())
    await p.stop()
    # 8000 voiced samples (500 ms) then 8000 silent: 25 frames of 20 ms, all on the origin clock.
    assert len(recorder.frames) == 50
    assert recorder.frames[0] == (origin, origin + 20, True)
    assert recorder.frames[-1] == (origin + 980, origin + 1000, False)
    assert sum(1 for *_, voiced in recorder.frames if voiced) == 25
    (final,) = recorder.finals
    assert final.text == "안녕하세요"
    assert final.utterance_id == "u1"
    assert final.start_ms == origin  # same clock as the frames; no pre-roll before the origin
    assert final.voiced_ms == 500
    assert final.end_ms > final.start_ms


@pytest.mark.asyncio
async def test_a_failed_recognition_hands_over_no_final() -> None:
    p = delivery_pipeline(Talker(None))
    p.interview = recorder = Recorder()
    await start_at(p)
    await feed(p, voiced_then_silence())
    await p.stop()
    assert recorder.finals == []


@pytest.mark.asyncio
async def test_transcripts_reach_the_run_even_with_speech_feedback_off() -> None:
    p = delivery_pipeline(
        Talker("끝까지 잘 들립니다"), speech_rate_enabled=False, filler_words_enabled=False
    )
    p.interview = recorder = Recorder()
    await start_at(p)
    await feed(p, voiced_then_silence())
    await p.stop()
    assert [f.text for f in recorder.finals] == ["끝까지 잘 들립니다"]


@pytest.mark.asyncio
async def test_running_phase_starts_the_run_and_stop_ends_it_before_the_report() -> None:
    p = delivery_pipeline(Talker())
    p.interview = recorder = Recorder()
    await p.prepare()
    assert recorder.calls == []  # not while the model is only preparing or calibrating
    await p.start_running()
    assert recorder.calls == ["start"]
    assert recorder.origin == p.audio_origin_ms  # questions are timed from the audio origin
    report = await p.stop()
    assert recorder.calls == ["start", "stop", "finalize"]
    assert report["interview_items"] == [{"question_id": "q1"}]
    await p.stop()  # a repeated stop returns the cached report without touching the run
    assert recorder.calls == ["start", "stop", "finalize"]


@pytest.mark.asyncio
async def test_report_has_no_interview_items_without_a_run() -> None:
    p = delivery_pipeline(Talker())
    await start_at(p)
    assert "interview_items" not in await p.stop()


@pytest.mark.asyncio
async def test_pending_finals_counts_the_speech_queue_and_the_utterance_being_spoken() -> None:
    gate = asyncio.Event()

    class Slow:
        async def infer(self, media):
            await gate.wait()
            return await Talker("네").infer(media)

    p = delivery_pipeline(Slow())
    await start_at(p)
    assert p.pending_finals() == 0
    # Voice that has not ended yet: the final of that utterance is still to come.
    await p.audio_queue.put(
        MediaPayload(p.session_id, p.audio_origin_ms, LOUD * 3200, format="pcm16")
    )
    await p.audio_queue.join()
    assert p.pending_finals() == 1
    # Endpoint reached: the utterance sits in the queue or in flight, still one pending final.
    await p.audio_queue.put(
        MediaPayload(
            p.session_id,
            p.audio_origin_ms + 200,
            QUIET * 9600,
            start_sample=3200,
            format="pcm16",
        )
    )
    await p.audio_queue.join()
    await asyncio.sleep(0.01)  # the speech worker picks it up and blocks in the model
    assert p.pending_finals() == 1
    gate.set()
    await p.speech_queue.join()
    assert p.pending_finals() == 0
    await p.stop()


@pytest.mark.asyncio
async def test_a_run_that_never_started_adds_nothing_to_the_report() -> None:
    p = delivery_pipeline(Talker())
    p.interview = recorder = Recorder()
    await p.prepare()  # ready, but never running (calibration did not finish)
    report = await p.stop()
    assert "interview_items" not in report
    assert "finalize" not in recorder.calls


@pytest.mark.parametrize("delivery_failed", [False, True])
@pytest.mark.asyncio
async def test_an_interview_gets_frames_and_finals_whatever_the_toggles_say(
    delivery_failed,
) -> None:
    p = delivery_pipeline(
        Talker("토글과 상관없이 들립니다"),
        delivery_enabled=False,
        speech_rate_enabled=False,
        filler_words_enabled=False,
    )
    p.interview = recorder = Recorder()
    await start_at(p)
    p.delivery_failed = delivery_failed
    await feed(p, voiced_then_silence())
    await p.stop()
    assert len(recorder.frames) == 50
    assert [f.text for f in recorder.finals] == ["토글과 상관없이 들립니다"]
