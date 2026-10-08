import asyncio
import threading
from uuid import uuid4

import pytest

from app.ai.base import AIResult, MediaPayload
from app.core.config import Settings
from app.realtime.pipeline import SessionPipeline
from app.realtime.state import SessionStateStore
from tests.fake_ai import FakeSpeechAdapter


def make_pipeline(speech=None, **options):
    return SessionPipeline(
        uuid4(),
        Settings(_env_file=None, **options),
        SessionStateStore(None),
        object(),
        speech or FakeSpeechAdapter(),
        {"gaze_enabled": False, "pronunciation_enabled": False},
    )


@pytest.mark.asyncio
async def test_preparing_has_no_audio_or_practice_clock():
    pipeline = make_pipeline()
    assert hasattr(pipeline, "prepare"), "explicit preparation missing"
    await pipeline.prepare()
    assert pipeline.phase == "preparing"
    assert not await pipeline.push_audio(0, b"audio")
    await pipeline.start_calibration()
    assert pipeline.phase == "running"
    assert pipeline.running_started_ms is not None
    await pipeline.stop()


@pytest.mark.asyncio
async def test_stop_waits_for_short_accepted_pcm_tail():
    import struct

    from app.modules.speech.segments import SpeechSegmenter

    received = []

    class Speech:
        async def infer(self, media):
            await asyncio.sleep(0.01)
            received.append(media)
            return AIResult("speech_rate", media.timestamp_ms, "info", "ok", {}, "네", True)

    pipeline = make_pipeline(Speech())
    pipeline.segmenter = SpeechSegmenter(is_speech=lambda _: True)
    await pipeline.start()
    assert hasattr(pipeline, "accept_media"), "validated packet acceptance missing"
    packet = MediaPayload(
        pipeline.session_id,
        pipeline.audio_origin_ms,
        struct.pack("<h", 1000) * 1600,
        1,
        0,
        1600,
        "pcm16",
    )
    await pipeline.accept_media(packet)
    report = await pipeline.stop()
    assert len(received) == 1
    assert received[0].sample_count == 1600
    assert report["transcript"] == "네"


@pytest.mark.asyncio
async def test_timeout_reports_incomplete_and_no_late_feedback():
    class Speech:
        async def infer(self, media):
            await asyncio.sleep(1)
            return AIResult("speech_rate", 0, "info", "ok", {}, "late", True)

    pipeline = make_pipeline(Speech(), pipeline_grace_seconds=0.01)
    await pipeline.start()
    await pipeline.push_audio(0, b"audio")
    report = await pipeline.stop()
    assert report["incomplete"] is True
    assert getattr(pipeline, "phase", None) == "completed"


@pytest.mark.asyncio
async def test_cancelled_native_inference_stays_busy_until_real_finish():
    import app.ai.base as base

    gate_type = getattr(base, "InferenceGate", None)
    assert gate_type is not None, "native inference gate missing"
    gate = gate_type()
    release = threading.Event()
    started = threading.Event()

    def slow():
        started.set()
        release.wait(2)
        return 7

    task = asyncio.create_task(gate.run_once(slow))
    await asyncio.to_thread(started.wait, 1)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert gate.busy
    with pytest.raises(RuntimeError, match="busy"):
        await gate.run_once(lambda: 8)
    release.set()
    for _ in range(100):
        if not gate.busy:
            break
        await asyncio.sleep(0.005)
    assert await gate.run_once(lambda: 9) == 9


@pytest.mark.asyncio
async def test_event_delivery_does_not_reorder_sequences():
    pipeline = make_pipeline()
    delivered = []

    async def delayed(event):
        if event.sequence == 1:
            await asyncio.sleep(0.03)
        delivered.append(event.sequence)

    pipeline.subscribe("order", delayed)
    await asyncio.gather(pipeline.emit("pong", 0, {}), pipeline.emit("pong", 0, {}))
    assert delivered == [1, 2]


@pytest.mark.asyncio
async def test_audio_replay_with_changed_samples_is_error_not_ack():
    pipeline = make_pipeline()
    await pipeline.start()
    try:
        await pipeline.accept_media(
            MediaPayload(
                pipeline.session_id, pipeline.audio_origin_ms, b"\0\0" * 8, 1, 0, 8, "pcm16"
            )
        )
        with pytest.raises(ValueError, match="REPLAY"):
            await pipeline.accept_media(
                MediaPayload(
                    pipeline.session_id, pipeline.audio_origin_ms, b"AB" * 8, 1, 0, 8, "pcm16"
                )
            )
    finally:
        await pipeline.stop()
