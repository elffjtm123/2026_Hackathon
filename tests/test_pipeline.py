import asyncio
from uuid import uuid4

import pytest

from app.ai.base import AIResult
from app.core.config import Settings
from app.modules.gaze.service import GazeStabilizer
from app.realtime.aggregator import FeedbackAggregator
from app.realtime.pipeline import SessionPipeline
from app.realtime.queues import DropOldestQueue
from app.realtime.state import SessionStateStore
from tests.fake_ai import FakeSpeechAdapter
from tests.test_gaze_service import gaze_result


def test_video_queue_drops_oldest() -> None:
    queue: DropOldestQueue[int] = DropOldestQueue(2)
    queue.put_latest(1)
    queue.put_latest(2)
    queue.put_latest(3)
    assert queue.stats.dropped == 1
    assert queue.queue.get_nowait() == 2
    assert queue.queue.get_nowait() == 3


def test_overlapping_final_transcripts_are_merged_once() -> None:
    aggregator = FeedbackAggregator()
    aggregator.add(
        AIResult(
            "speech_rate",
            1000,
            "info",
            "ok",
            {"syllables_per_minute": 200, "duration_sec": 2},
            "음 저는 백엔드",
            True,
        )
    )
    aggregator.add(
        AIResult(
            "speech_rate",
            2750,
            "info",
            "ok",
            {"syllables_per_minute": 220, "duration_sec": 2},
            "백엔드 개발자입니다",
            True,
        )
    )

    report = aggregator.report()

    assert report["transcript"] == "음 저는 백엔드 개발자입니다"
    assert report["filler_word_counts"] == {"음": 1}


def test_gaze_away_duration_uses_sample_timestamps() -> None:
    aggregator = FeedbackAggregator()
    aggregator.add(gaze_result(1000, True, "left"))
    aggregator.add(gaze_result(1750, True, "left"))
    aggregator.add(gaze_result(2500, True, "center"))

    assert aggregator.report()["gaze_away_duration_ms"] == 1500


@pytest.mark.asyncio
async def test_transcript_without_confidence_skips_pronunciation_feedback() -> None:
    settings = Settings(jwt_secret="test-secret-that-is-definitely-long-enough", redis_url=None)
    pipeline = SessionPipeline(
        uuid4(), settings, SessionStateStore(None), object(), FakeSpeechAdapter(), {}
    )
    events = []

    async def collect(event: object) -> None:
        events.append(event)

    pipeline.subscribe("test", collect)  # type: ignore[arg-type]
    await pipeline._handle_transcript_analysis(
        AIResult("speech_rate", 100, "info", "ok", {}, "안녕하세요", True)
    )
    assert events == []


@pytest.mark.asyncio
async def test_slow_failing_gaze_does_not_stop_speech() -> None:
    class FailingGaze:
        async def infer(self, media: object) -> object:
            await asyncio.sleep(0.02)
            raise RuntimeError("boom")

    settings = Settings(jwt_secret="test-secret-that-is-definitely-long-enough", redis_url=None)
    pipeline = SessionPipeline(
        uuid4(),
        settings,
        SessionStateStore(None),
        FailingGaze(),  # type: ignore[arg-type]
        FakeSpeechAdapter(),
        {"gaze_enabled": True, "speech_rate_enabled": True},
    )
    events = []

    async def collect(event: object) -> None:
        events.append(event)

    pipeline.subscribe("test", collect)  # type: ignore[arg-type]
    await pipeline.start()
    await pipeline.push_video(100, b"jpeg")
    await pipeline.push_audio(100, "음 저는 개발자입니다".encode())
    await asyncio.sleep(0.1)
    report = await pipeline.stop()
    assert any(event.event == "error" for event in events)
    assert any(
        event.event == "feedback" and event.data["source"] == "speech_rate" for event in events
    )
    assert report["filler_word_counts"] == {"음": 1}
    assert report["incomplete"] is True


@pytest.mark.asyncio
async def test_failing_speech_does_not_stop_gaze() -> None:
    class WorkingGaze:
        async def infer(self, media: object) -> AIResult:
            return AIResult("gaze", 100, "info", "ok", {"away": False})

    class FailingSpeech:
        async def infer(self, media: object) -> object:
            raise RuntimeError("boom")

    settings = Settings(jwt_secret="test-secret-that-is-definitely-long-enough", redis_url=None)
    pipeline = SessionPipeline(
        uuid4(),
        settings,
        SessionStateStore(None),
        WorkingGaze(),  # type: ignore[arg-type]
        FailingSpeech(),  # type: ignore[arg-type]
        {"gaze_enabled": True, "speech_rate_enabled": True},
    )
    events = []

    async def collect(event: object) -> None:
        events.append(event)

    pipeline.subscribe("test", collect)  # type: ignore[arg-type]
    await pipeline.start()
    await pipeline.push_audio(100, b"audio")
    await pipeline.push_video(100, b"jpeg")
    await asyncio.sleep(0.05)
    report = await pipeline.stop()

    assert any(
        event.event == "error" and event.data["code"] == "SPEECH_AI_UNAVAILABLE" for event in events
    )
    assert any(event.event == "feedback" and event.data["source"] == "gaze" for event in events)
    assert report["transcript"] is None
    assert report["incomplete"] is True
    assert not any(
        event.event == "feedback" and event.data["source"] == "speech_rate" for event in events
    )


@pytest.mark.asyncio
async def test_stop_drains_audio_and_emits_completion_once() -> None:
    settings = Settings(
        jwt_secret="test-secret-that-is-definitely-long-enough",
        redis_url=None,
        pipeline_grace_seconds=1,
    )
    pipeline = SessionPipeline(
        uuid4(),
        settings,
        SessionStateStore(None),
        object(),  # type: ignore[arg-type]
        FakeSpeechAdapter(),
        {"speech_rate_enabled": True, "pronunciation_enabled": False},
    )
    events = []

    async def collect(event: object) -> None:
        events.append(event)

    pipeline.subscribe("test", collect)  # type: ignore[arg-type]
    await pipeline.start()
    await pipeline.push_audio(100, "마지막 문장입니다".encode())
    first = await pipeline.stop()
    second = await pipeline.stop()

    assert first["transcript"] == "마지막 문장입니다"
    assert second == first
    assert [event.event for event in events].count("session.completed") == 1
    assert events[-1].data["report"]["incomplete"] is False


@pytest.mark.asyncio
async def test_recalibration_does_not_reset_running_audio_clock():
    settings = Settings(jwt_secret="test-secret-that-is-definitely-long-enough", redis_url=None)
    pipeline = SessionPipeline(
        uuid4(), settings, SessionStateStore(None), object(), FakeSpeechAdapter(), {}
    )
    await pipeline.start()
    origin = pipeline.audio_origin_ms
    await pipeline.start_calibration()
    assert pipeline.phase == "running"
    assert pipeline.audio_origin_ms == origin
    assert pipeline.gaze_stabilizer.calibration_status == "collecting"
    await pipeline.stop()


@pytest.mark.asyncio
@pytest.mark.parametrize("recalibrate", [True, False])
async def test_old_or_delayed_gaze_result_cannot_become_fresh(recalibrate):
    entered, release, published = asyncio.Event(), asyncio.Event(), asyncio.Event()

    class SlowGaze:
        async def infer(self, media):
            entered.set()
            await release.wait()
            result = gaze_result(media.timestamp_ms, True, "center")
            if recalibrate:
                result.metrics["quality_flags"] = ["face_changed"]
            return result

    settings = Settings(jwt_secret="test-secret-that-is-definitely-long-enough", redis_url=None)
    pipeline = SessionPipeline(
        uuid4(), settings, SessionStateStore(None), SlowGaze(), FakeSpeechAdapter(), {}
    )
    pipeline.protocol = 2
    events = []

    async def collect(event):
        if event.event == "feedback":
            events.append(event)
            published.set()

    pipeline.subscribe("test", collect)
    await pipeline.start()
    pipeline.gaze_stabilizer = GazeStabilizer()
    clock = 0
    pipeline.elapsed_ms = lambda: clock
    try:
        await pipeline.push_video(0, b"jpeg")
        await entered.wait()
        if recalibrate:
            clock = 100
            await pipeline.start_calibration()
        else:
            clock = 6000
        release.set()
        await pipeline.video_queue.queue.join()
        if recalibrate:
            assert pipeline.gaze_stabilizer.calibration_status == "collecting"
            assert not events
        else:
            assert events[-1].data["metrics"]["attention_state"] == "unknown"
            assert "stale_observation" in events[-1].data["metrics"]["quality_flags"]
    finally:
        release.set()
        await pipeline.stop()
