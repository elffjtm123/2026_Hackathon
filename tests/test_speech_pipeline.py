import asyncio
import struct
from uuid import uuid4

import pytest

from app.ai.base import AIResult, MediaPayload
from app.core.config import Settings
from app.modules.speech.segments import SpeechSegmenter
from app.realtime.pipeline import SessionPipeline
from app.realtime.state import SessionStateStore


@pytest.mark.asyncio
async def test_script_timing_uses_final_end_not_start():
    p = pipeline(object())
    p.update_analysis_settings({"script": "시스템 기능을 소개합니다.", "time_limit_seconds": 8})
    p.running_started_ms = 2000
    events = []

    async def collect(event):
        events.append(event)

    p.subscribe("test", collect)
    await p._handle_transcript_analysis(
        AIResult(
            "speech_rate", 2000, "info", "", {"end_ms": 10000}, "시스템 기능을 소개합니다.", True
        )
    )
    progress = next(e.data for e in events if e.event == "script.progress")
    assert progress["pace_status"] == "on_time"
    assert progress["pace_delta_ms"] == 0


@pytest.mark.asyncio
async def test_silence_feedback_has_no_filler_analysis():
    p = pipeline(object())
    p.phase = "running"
    events = []

    async def collect(event):
        events.append(event)

    p.subscribe("test", collect)
    await p._handle_result(
        AIResult(
            "speech_rate",
            2000,
            "info",
            "음성 대기 중입니다.",
            {"pace": "unknown", "filler_counts": {}},
        )
    )
    assert events[0].data["metrics"]["filler_status"] == "unavailable"


def pipeline(speech):
    result = SessionPipeline(
        uuid4(),
        Settings(_env_file=None),
        SessionStateStore(None),
        object(),
        speech,
        {"gaze_enabled": False, "pronunciation_enabled": False},
    )
    result.segmenter = SpeechSegmenter(is_speech=lambda pcm: struct.unpack_from("<h", pcm)[0] > 0)
    return result


@pytest.mark.asyncio
async def test_endpoint_transcribes_before_two_seconds_and_stop_keeps_tail():
    heard = []
    inferred = asyncio.Event()

    class Speech:
        async def infer(self, media):
            heard.append(media)
            inferred.set()
            return AIResult("speech_rate", media.timestamp_ms, "info", "ok", {}, "네", True)

    p = pipeline(Speech())
    await p.start()
    try:
        pcm = struct.pack("<h", 1000) * 1600 + b"\0\0" * 8000
        await p.audio_queue.put(MediaPayload(p.session_id, p.audio_origin_ms, pcm, format="pcm16"))
        await asyncio.wait_for(inferred.wait(), 0.5)
        assert heard[0].voiced_ms == 100
        assert heard[0].end_ms - heard[0].timestamp_ms == 200
        await p.audio_queue.put(
            MediaPayload(
                p.session_id,
                p.audio_origin_ms + 600,
                struct.pack("<h", 1000) * 1600,
                start_sample=9600,
                format="pcm16",
            )
        )
    finally:
        report = await p.stop()
    assert report["transcript"] == "네 네"
    assert report["incomplete"] is False
    assert len(heard) == 2
    assert heard[0].utterance_id != heard[1].utterance_id


@pytest.mark.asyncio
async def test_silent_packets_never_reach_model():
    class Speech:
        async def infer(self, media):
            raise AssertionError("silence reached model")

    p = pipeline(Speech())
    await p.start()
    await p.audio_queue.put(
        MediaPayload(p.session_id, p.audio_origin_ms, b"\0\0" * 32000, format="pcm16")
    )
    report = await p.stop()
    assert report["incomplete"] is False
    assert report["transcript"] is None


@pytest.mark.asyncio
async def test_slow_model_does_not_block_packet_segmentation_or_silently_overflow():
    release, entered = asyncio.Event(), asyncio.Event()

    class Speech:
        async def infer(self, media):
            entered.set()
            await release.wait()
            return AIResult("speech_rate", media.timestamp_ms, "info", "ok", {}, "네", True)

    p = pipeline(Speech())
    errors = []

    async def collect(event):
        if event.event == "error":
            errors.append(event.data["code"])

    p.subscribe("test", collect)
    await p.start()
    try:
        for index in range(5):
            await p.audio_queue.put(
                MediaPayload(
                    p.session_id,
                    p.audio_origin_ms + index * 600,
                    struct.pack("<h", 1000) * 1600 + b"\0\0" * 8000,
                    start_sample=index * 9600,
                    format="pcm16",
                )
            )
        await asyncio.wait_for(entered.wait(), 0.5)
        await asyncio.wait_for(p.audio_queue.join(), 1)
        assert "UTTERANCE_QUEUE_FULL" in errors
    finally:
        release.set()
        report = await p.stop()
    assert report["incomplete"] is True


@pytest.mark.asyncio
async def test_disabled_features_skip_already_queued_inference():
    class Speech:
        async def infer(self, media):
            raise AssertionError("disabled modules reached model")

    p = pipeline(Speech())
    p.analysis_settings.update(speech_rate_enabled=False, filler_words_enabled=False)
    await p.start()
    await p.speech_queue.put(MediaPayload(p.session_id, 0, b"legacy-audio"))
    report = await p.stop()
    assert report["incomplete"] is False
    assert report["transcript"] is None


@pytest.mark.asyncio
async def test_late_final_preserves_transcript_but_not_expired_live_rate():
    entered, release = asyncio.Event(), asyncio.Event()

    class Speech:
        async def infer(self, media):
            entered.set()
            await release.wait()
            return AIResult("speech_rate", media.timestamp_ms, "info", "ok", {}, "가" * 20, True)

    p = pipeline(Speech())
    feedback = []

    async def collect(event):
        if event.event == "feedback":
            feedback.append(event.data)

    p.subscribe("test", collect)
    await p.start()
    try:
        await p.audio_queue.put(
            MediaPayload(
                p.session_id,
                p.audio_origin_ms,
                struct.pack("<h", 1000) * 32000 + b"\0\0" * 8000,
                format="pcm16",
            )
        )
        await asyncio.wait_for(entered.wait(), 0.5)
        await p.audio_queue.put(
            MediaPayload(
                p.session_id,
                p.audio_origin_ms + 2500,
                b"\0\0" * 200000,
                start_sample=40000,
                format="pcm16",
            )
        )
        await p.audio_queue.put(
            MediaPayload(
                p.session_id,
                p.audio_origin_ms + 15000,
                struct.pack("<h", 1000) * 3200,
                start_sample=240000,
                format="pcm16",
            )
        )
        await asyncio.wait_for(p.audio_queue.join(), 0.5)
        release.set()
        await asyncio.wait_for(p.speech_queue.join(), 0.5)
        final = next(item for item in feedback if item.get("transcript"))
        assert final["metrics"]["pace"] == "unknown"
        assert final["metrics"]["syllables_per_minute"] is None
        assert final["metrics"]["warning_episode_count"] == 0
        assert p.aggregator.syllable_count == 20
    finally:
        release.set()
        await p.stop()


@pytest.mark.asyncio
async def test_slow_state_store_cannot_publish_final_warning_after_silence():
    entered, release = asyncio.Event(), asyncio.Event()
    waiting = asyncio.Event()

    class Store(SessionStateStore):
        async def set(self, session_id, value):
            if value.get("average_syllables_per_minute") and not entered.is_set():
                entered.set()
                await release.wait()
            await super().set(session_id, value)

    class Speech:
        async def infer(self, media):
            return AIResult("speech_rate", media.timestamp_ms, "info", "ok", {}, "가" * 20, True)

    p = pipeline(Speech())
    p.state_store = Store(None)
    handle_result = p._handle_result

    async def observe(result):
        if not result.is_final and result.metrics.get("pace") == "unknown":
            waiting.set()
        await handle_result(result)

    p._handle_result = observe
    feedback = []

    async def collect(event):
        if event.event == "feedback":
            feedback.append(event.data)

    p.subscribe("test", collect)
    await p.start()
    try:
        await p.audio_queue.put(
            MediaPayload(
                p.session_id,
                p.audio_origin_ms,
                struct.pack("<h", 1000) * 32000 + b"\0\0" * 8000,
                format="pcm16",
            )
        )
        await asyncio.wait_for(entered.wait(), 0.5)
        await p.audio_queue.put(
            MediaPayload(
                p.session_id,
                p.audio_origin_ms + 2500,
                b"\0\0" * 32000,
                start_sample=40000,
                format="pcm16",
            )
        )

        await asyncio.wait_for(waiting.wait(), 0.5)
        await asyncio.sleep(0)
        release.set()
        await asyncio.wait_for(p.audio_queue.join(), 0.5)
        await asyncio.wait_for(p.speech_queue.join(), 0.5)
        assert feedback[-1]["metrics"]["pace"] == "unknown"
        assert p.aggregator.last_speech_pace == "unknown"
        assert p.aggregator.transcript == "가" * 20
    finally:
        release.set()
        await p.stop()


@pytest.mark.asyncio
async def test_speech_completed_in_each_packet_clears_waiting():
    class Speech:
        async def infer(self, media):
            return AIResult("speech_rate", media.timestamp_ms, "info", "ok", {}, "가" * 20, True)

    p = pipeline(Speech())
    await p.start()
    try:
        await p.audio_queue.put(
            MediaPayload(
                p.session_id,
                p.audio_origin_ms,
                b"\0\0" * 32000,
                format="pcm16",
            )
        )
        await p.audio_queue.join()
        assert p.speech_waiting
        for index in range(4):
            await p.audio_queue.put(
                MediaPayload(
                    p.session_id,
                    p.audio_origin_ms + 2000 + index * 1000,
                    struct.pack("<h", 1000) * 8000 + b"\0\0" * 8000,
                    start_sample=32000 + index * 16000,
                    format="pcm16",
                )
            )
            await p.audio_queue.join()
            await p.speech_queue.join()
        assert not p.speech_waiting
        assert p.aggregator.last_speech_pace == "fast"
        assert p.aggregator.speech_warning_episodes == 1
        assert p.aggregator.voiced_ms == 2000
    finally:
        await p.stop()
