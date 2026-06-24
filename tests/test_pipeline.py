import asyncio
from uuid import uuid4

import pytest

from app.ai.mock import MockSpeechAdapter
from app.core.config import Settings
from app.realtime.pipeline import SessionPipeline
from app.realtime.queues import DropOldestQueue
from app.realtime.state import SessionStateStore


def test_video_queue_drops_oldest() -> None:
    queue: DropOldestQueue[int] = DropOldestQueue(2)
    queue.put_latest(1)
    queue.put_latest(2)
    queue.put_latest(3)
    assert queue.stats.dropped == 1
    assert queue.queue.get_nowait() == 2
    assert queue.queue.get_nowait() == 3


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
        MockSpeechAdapter(),
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
