"""Seam: SessionPipeline.suspend() / resume() (round break) with a recording model runtime."""

import asyncio
from uuid import uuid4

import pytest

from app.ai.base import AIResult, MediaPayload
from app.ai.model_execution import ModelExecution
from app.modules.interview.questions import FinalUtterance
from tests.test_delivery_pipeline import (  # noqa: F401  (vad is a fixture, used by name below)
    LOUD,
    QUIET,
    delivery_pipeline,
    start_at,
    vad,
)

pytestmark = pytest.mark.usefixtures("vad")


class Runtime:
    """Realtime runtime double that records what happens to it, in order."""

    def __init__(self, order: list[str]) -> None:
        self.order = order
        self.starts = self.stops = 0
        self.modules: dict = {}
        self.stopping = asyncio.Event()
        self.starting = asyncio.Event()
        self.finish_stop = asyncio.Event()
        self.finish_stop.set()
        self.finish_start = asyncio.Event()
        self.finish_start.set()

    async def start(self) -> None:
        self.starts += 1
        self.order.append("runtime.start")
        self.starting.set()
        await self.finish_start.wait()

    async def stop(self) -> None:
        self.order.append("runtime.stop")
        self.stopping.set()
        await self.finish_stop.wait()
        self.stops += 1


class Talker:
    def __init__(self, order: list[str], *texts: str) -> None:
        self.order, self.texts = order, list(texts)

    async def infer(self, media):
        self.order.append("infer")
        text = self.texts.pop(0) if self.texts else "네"
        return AIResult("speech_rate", media.timestamp_ms, "info", "ok", {}, text, True)


class Run:
    """Stands in for an InterviewRun."""

    started = False

    def __init__(self) -> None:
        self.finals: list[FinalUtterance] = []

    async def start(self, origin_ms=None) -> None:
        self.started = True

    async def stop(self) -> None:
        pass

    def finalize(self) -> list[dict]:
        return []

    def observe_frame(self, *args) -> None:
        pass

    def on_final(self, utterance: FinalUtterance) -> None:
        self.finals.append(utterance)


class Setup:
    def __init__(self, *texts: str) -> None:
        self.order: list[str] = []
        self.runtime = Runtime(self.order)
        self.execution = ModelExecution(self.runtime)
        self.pipeline = delivery_pipeline(Talker(self.order, *texts))
        self.pipeline.execution = self.execution
        self.events: list[str] = []
        self.data: dict[str, dict] = {}

        async def collect(event) -> None:
            self.events.append(event.event)
            self.data[event.event] = event.data

        self.pipeline.subscribe("test", collect)
        self.run = Run()
        self.pipeline.interview = self.run


def media(p, sequence: int, start_sample: int, pcm: bytes) -> MediaPayload:
    count = len(pcm) // 2
    return MediaPayload(
        p.session_id,
        p.audio_origin_ms + start_sample // 16,
        pcm,
        sequence,
        start_sample,
        count,
        "pcm16",
    )


async def done_within(awaitable, timeout=3):
    task = asyncio.ensure_future(awaitable)
    done, _ = await asyncio.wait({task}, timeout=timeout)
    assert done, "hung"
    return task.result()


async def started(*texts: str) -> Setup:
    s = Setup(*texts)
    await start_at(s.pipeline)
    return s


async def test_suspend_transcribes_the_speech_tail_before_the_runtime_stops() -> None:
    s = await started("안녕하세요")
    p = s.pipeline
    await p.accept_media(media(p, 1, 0, LOUD * 8000))  # speech still running, no endpoint yet
    await p.audio_queue.join()
    assert s.run.finals == []
    await p.suspend()
    assert [f.text for f in s.run.finals] == ["안녕하세요"]
    assert s.order == ["runtime.start", "infer", "runtime.stop"]
    assert p.phase == "suspended" and p.tasks == [] and p.speech_queue.empty()
    assert s.events[-1] == "session.suspended"
    assert s.runtime.stops == 1 and s.execution.owner == p.session_id  # ownership is kept


async def test_resume_restarts_the_runtime_and_workers_and_reports_the_same_audio_origin() -> None:
    s = await started()
    p = s.pipeline
    origin = p.audio_origin_ms
    await p.suspend()
    await p.resume()
    assert s.order == ["runtime.start", "runtime.stop", "runtime.start"]
    assert p.phase == "running" and p.accepting and len(p.tasks) == 3
    assert s.events[-2:] == ["session.suspended", "session.resumed"]
    assert s.data["session.resumed"]["audio_origin_ms"] == origin == p.audio_origin_ms
    await p.stop()


async def test_media_during_the_break_is_dropped_without_errors_and_audio_is_acknowledged() -> None:
    s = await started()
    p = s.pipeline
    await p.suspend()
    await p.accept_media(media(p, 1, 0, LOUD * 3200))
    await p.accept_media(MediaPayload(p.session_id, 5, b"jpeg", 1, 0, 0, "jpeg"))
    assert p.audio_queue.empty() and p.video_queue.qsize() == 0
    assert not p.incomplete and "error" not in s.events
    assert s.data["media.ack"] == {"media_type": "audio", "accepted_sequence": 1}
    await p.push_video(10, b"x")  # the websocket-less entry points are silent too
    assert not await p.push_audio(10, b"\0\0")
    assert p.video_queue.qsize() == 0


async def test_audio_after_the_break_may_skip_ahead_then_must_be_contiguous() -> None:
    s = await started("안녕하세요", "다시 시작합니다")
    p = s.pipeline
    await p.accept_media(media(p, 1, 0, LOUD * 8000 + QUIET * 8000))
    await p.audio_queue.join()
    await p.speech_queue.join()
    await p.suspend()
    await p.accept_media(media(p, 2, 16000, LOUD * 3200))  # dropped, but counted
    p.started_monotonic -= 30  # the break lasts a while
    await p.resume()
    # The client stopped sending for a while: sequence and sample position jump ahead.
    start = (p.elapsed_ms() - p.audio_origin_ms - 100) * 16  # where the session clock is now
    await p.accept_media(media(p, 5, start, LOUD * 8000))
    await p.accept_media(media(p, 6, start + 8000, QUIET * 8000))
    await p.audio_queue.join()
    await p.speech_queue.join()
    first, second = s.run.finals
    assert (first.utterance_id, first.text) == ("u1", "안녕하세요")
    assert (second.utterance_id, second.text) == ("u2", "다시 시작합니다")  # ids keep counting
    assert second.start_ms == p.audio_origin_ms + start // 16  # same audio timeline
    with pytest.raises(ValueError, match="MEDIA_SEQUENCE_GAP"):
        await p.accept_media(media(p, 8, start + 16000, QUIET * 160))
    await p.stop()


async def test_a_client_that_kept_sending_through_the_break_continues_seamlessly() -> None:
    s = await started("안녕하세요")
    p = s.pipeline
    await p.suspend()
    await p.accept_media(media(p, 1, 0, LOUD * 3200))
    await p.accept_media(media(p, 2, 3200, LOUD * 3200))
    await p.resume()
    await p.accept_media(media(p, 3, 6400, LOUD * 3200))  # contiguous with what was dropped
    assert not p.incomplete
    await p.stop()


async def test_stop_while_suspended_finishes_without_the_drain_and_releases_ownership() -> None:
    s = await started("네")
    p = s.pipeline
    await p.suspend()
    report = await done_within(p.stop())
    assert p.phase == "completed" and report["incomplete"] is False
    assert s.events[-1] == "session.completed"
    assert s.runtime.stops == 1  # already stopped by the suspend, not stopped twice
    assert s.execution.owner is None
    assert s.run.started


async def test_the_report_leaves_out_the_break() -> None:
    s = await started()
    p = s.pipeline
    await p.suspend()
    p.started_monotonic -= 30  # a 30 s break
    await p.resume()
    report = await p.stop()
    wall = p.elapsed_ms() - p.running_started_ms
    assert 0 <= report["summary"]["duration_ms"] <= wall - 29_000


async def test_a_stop_during_the_break_closes_the_open_break_in_the_report() -> None:
    s = await started()
    p = s.pipeline
    await p.suspend()
    p.started_monotonic -= 30
    report = await p.stop()
    wall = p.elapsed_ms() - p.running_started_ms
    assert 0 <= report["summary"]["duration_ms"] <= wall - 29_000


async def test_stop_while_the_runtime_is_stopping_is_safe_and_suspend_does_not_resurface() -> None:
    s = await started()
    p = s.pipeline
    s.runtime.finish_stop.clear()
    suspending = asyncio.create_task(p.suspend())
    await done_within(s.runtime.stopping.wait())
    stopping = asyncio.create_task(p.stop())
    await asyncio.sleep(0.05)
    s.runtime.finish_stop.set()
    report = await done_within(stopping)
    await done_within(asyncio.gather(suspending, return_exceptions=True))
    assert p.phase == "completed" and report is p.completed_report
    assert "session.suspended" not in s.events
    assert s.events[-1] == "session.completed"
    assert s.execution.owner is None


async def test_stop_while_the_runtime_is_restarting_is_safe_and_resume_does_not_resurface() -> None:
    s = await started()
    p = s.pipeline
    await p.suspend()
    s.runtime.starting.clear()
    s.runtime.finish_start.clear()
    resuming = asyncio.create_task(p.resume())
    await done_within(s.runtime.starting.wait())
    report = await done_within(p.stop())
    await done_within(asyncio.gather(resuming, return_exceptions=True))
    assert p.phase == "completed" and report is p.completed_report
    assert "session.resumed" not in s.events and p.tasks == []
    assert s.execution.owner is None


async def test_suspend_and_resume_need_the_right_phase() -> None:
    s = await started()
    p = s.pipeline
    with pytest.raises(ValueError, match="INVALID_SESSION_STATE"):
        await p.resume()
    await p.suspend()
    with pytest.raises(ValueError, match="INVALID_SESSION_STATE"):
        await p.suspend()
    await p.resume()
    await p.stop()
    with pytest.raises(ValueError, match="INVALID_SESSION_STATE"):
        await p.suspend()


async def test_a_pipeline_without_execution_can_suspend_and_resume() -> None:
    order: list[str] = []
    p = delivery_pipeline(Talker(order))
    await start_at(p)
    await p.suspend()
    await p.resume()
    assert p.phase == "running" and len(p.tasks) == 3
    await p.stop()


async def test_a_pipeline_that_never_suspended_stops_as_before() -> None:
    s = await started("안녕하세요")
    p = s.pipeline
    await p.accept_media(media(p, 1, 0, LOUD * 8000))
    await p.audio_queue.join()
    report = await p.stop()  # the tail is drained by stop itself
    assert [f.text for f in s.run.finals] == ["안녕하세요"]
    assert "session.suspended" not in s.events and report["transcript"] == "안녕하세요"
    assert s.order == ["runtime.start", "infer", "runtime.stop"]


class FakeLlm:
    def __init__(self, order: list[str]) -> None:
        self.order = order

    def loaded(self):
        order = self.order

        class Loaded:
            async def __aenter__(self):
                order.append("llm.load")

            async def __aexit__(self, *exc):
                order.append("llm.unload")

        return Loaded()


async def test_the_generation_model_loads_only_while_the_realtime_runtime_is_stopped() -> None:
    s = await started()
    p = s.pipeline
    llm = FakeLlm(s.order)
    with pytest.raises(ValueError, match="SESSION_NOT_SUSPENDED"):
        async with s.execution.borrowing(p.session_id):
            pytest.fail("borrowing must not start before the suspend")
    await p.suspend()
    async with s.execution.borrowing(p.session_id):
        async with llm.loaded():
            assert s.execution.generation_active
    assert not s.execution.generation_active
    with pytest.raises(ValueError, match="SESSION_BUSY"):
        await s.execution.start_session(uuid4())  # another session
    await p.resume()
    assert s.order == [
        "runtime.start",
        "runtime.stop",
        "llm.load",
        "llm.unload",
        "runtime.start",
    ]
    await p.stop()
    assert s.execution.owner is None


@pytest.mark.parametrize("lag_ms", [0, 800, 1300, 2000])
async def test_a_client_whose_counter_kept_running_is_accepted_whatever_its_capture_lag(
    lag_ms,
) -> None:
    """Capture lags the session clock (it started after session.running) and a 200 ms packet
    is stamped at its start: the first packet after the resume is that old when it arrives."""
    s = await started("안녕하세요")
    p = s.pipeline
    await p.suspend()
    p.started_monotonic -= 30
    await p.resume()
    start = max(0, p.elapsed_ms() - p.audio_origin_ms - lag_ms - 200) * 16
    start -= start % 3200
    await p.accept_media(media(p, 1, start, LOUD * 8000))
    await p.accept_media(media(p, 2, start + 8000, QUIET * 8000))
    await p.audio_queue.join()
    await p.speech_queue.join()
    assert not p.incomplete and "error" not in s.events
    (final,) = s.run.finals  # the round-two answer reaches the interview
    assert final.start_ms == p.audio_origin_ms + start // 16
    await p.stop()


async def test_audio_from_a_counter_that_stalled_in_the_break_is_dropped_quietly(caplog) -> None:
    s = await started("안녕하세요")
    p = s.pipeline
    await p.suspend()
    p.started_monotonic -= 30
    await p.resume()
    acks = len([e for e in s.events if e == "media.ack"])
    # Stamped where the break began, 30 s in the past.
    with caplog.at_level("WARNING", logger="app.realtime.pipeline"):
        await p.accept_media(media(p, 1, 0, LOUD * 3200))
        await p.accept_media(media(p, 2, 3200, LOUD * 3200))
    # Not a client-visible error, but the report shows the contract was broken.
    assert p.incomplete and "error" not in s.events
    assert [r.message for r in caplog.records].count("audio_from_the_break_dropped") == 1
    assert len([e for e in s.events if e == "media.ack"]) == acks + 2  # acked, not queued
    assert p.audio_queue.empty() and p.segmenter is None
    start = (p.elapsed_ms() - p.audio_origin_ms - 200) * 16  # real-time audio follows
    await p.accept_media(media(p, 3, start, LOUD * 8000))
    await p.accept_media(media(p, 4, start + 8000, QUIET * 8000))
    await p.audio_queue.join()
    await p.speech_queue.join()
    assert [f.text for f in s.run.finals] == ["안녕하세요"]
    assert s.run.finals[0].start_ms == p.audio_origin_ms + start // 16
    await p.stop()


async def test_a_short_break_is_never_judged_stricter_than_the_capture_lag_allows() -> None:
    s = await started()
    p = s.pipeline
    await p.suspend()
    p.started_monotonic -= 2  # a 2 s break
    await p.resume()
    start = max(0, p.elapsed_ms() - p.audio_origin_ms - 2000) * 16
    start -= start % 3200
    await p.accept_media(media(p, 1, start, LOUD * 3200))
    assert p.next_audio_sample == start + 3200
    await p.stop()


async def test_samples_already_dropped_during_the_break_cannot_be_sent_again() -> None:
    s = await started()
    p = s.pipeline
    await p.suspend()
    await p.accept_media(media(p, 1, 0, LOUD * 3200))
    p.started_monotonic -= 30
    await p.resume()
    again = MediaPayload(p.session_id, p.elapsed_ms() - 100, LOUD * 6400, 2, 0, 3200, "pcm16")
    with pytest.raises(ValueError, match="MEDIA_SEQUENCE_GAP"):
        await p.accept_media(again)
    await p.stop()


async def test_stale_queue_items_do_not_survive_a_suspend_that_ran_out_of_time() -> None:
    s = Setup()
    calls = 0

    class Stuck:
        async def infer(self, media):
            nonlocal calls
            calls += 1
            if calls == 1:
                await asyncio.Event().wait()  # the first utterance never finishes
            return AIResult("speech_rate", media.timestamp_ms, "info", "ok", {}, "다시", True)

    s.pipeline.speech = Stuck()
    s.pipeline.settings.pipeline_grace_seconds = 0.1
    await start_at(s.pipeline)
    p = s.pipeline
    await p.accept_media(media(p, 1, 0, LOUD * 8000 + QUIET * 8000))
    await asyncio.sleep(0.05)
    await p.accept_media(media(p, 2, 16000, LOUD * 3200))
    await p.suspend()  # the grace period runs out
    assert p.incomplete
    assert p.audio_queue.empty() and p.speech_queue.empty() and p.video_queue.qsize() == 0
    p.started_monotonic -= 30
    await p.resume()
    start = (p.elapsed_ms() - p.audio_origin_ms - 100) * 16
    await p.accept_media(media(p, 3, start, LOUD * 8000))
    await p.accept_media(media(p, 4, start + 8000, QUIET * 8000))
    await p.audio_queue.join()
    await p.speech_queue.join()
    assert [f.text for f in s.run.finals] == ["다시"]  # round two is not deaf
    await p.stop()


async def test_the_delivery_analyzer_is_told_about_the_break() -> None:
    s = await started()
    p = s.pipeline
    await p.suspend()
    p.started_monotonic -= 30
    await p.resume()
    ((start, end),) = p.delivery.gaps
    assert end - start >= 30_000
    await p.suspend()
    p.started_monotonic -= 10
    await p.stop()  # stopped during the second break
    assert len(p.delivery.gaps) == 2 and p.delivery.gaps[1][0] >= end


async def test_the_gaze_calibration_survives_suspend_and_resume() -> None:
    from app.modules.gaze.service import GazeStabilizer
    from tests.test_gaze_service import gaze_result

    s = await started()
    p = s.pipeline
    p.gaze_stabilizer = GazeStabilizer()  # calibrated (baseline 0)
    p.gaze_stabilizer.update(gaze_result(1000, face_detected=True, direction="center"))
    await p.suspend()
    p.started_monotonic -= 60
    await p.resume()
    p.gaze_stabilizer.update(gaze_result(70_000, face_detected=True, direction="center"))
    assert not p.gaze_stabilizer.recalibration_required
    assert p.gaze_stabilizer.baseline_yaw == 0.0
    await p.stop()


async def test_speech_waiting_is_not_reported_just_because_the_break_was_long() -> None:
    s = await started()
    p = s.pipeline
    messages: list[str] = []

    async def collect(event) -> None:
        if event.event == "feedback":
            messages.append(event.data["message"])

    p.subscribe("messages", collect)
    await p.suspend()
    p.started_monotonic -= 30
    await p.resume()
    start = (p.elapsed_ms() - p.audio_origin_ms - 100) * 16
    await p.accept_media(media(p, 1, start, QUIET * 3200))
    await p.audio_queue.join()
    assert "음성 대기 중입니다." not in messages  # only 200 ms of quiet so far
    await p.stop()
