import json
import math
import struct
from dataclasses import asdict

import pytest

from app.ai.base import AIResult, MediaPayload
from app.modules.speech.segments import SpeechSegmenter
from tests.test_speech_pipeline import pipeline


def detector():
    from app.modules.speech.changes import SpeechChangeDetector

    return SpeechChangeDetector()


def volume(d, start, duration, rms, voiced=True):
    for at in range(start, start + duration, 20):
        d.observe_audio(at, at + 20, rms, voiced)


@pytest.mark.parametrize("factor,direction", [(3, "up"), (0.25, "down")])
def test_sustained_volume_changes_after_voice_baseline(factor, direction):
    d = detector()
    volume(d, 0, 3000, 0.04)
    assert not d.events
    volume(d, 3000, 500, 0.04 * factor)
    assert not d.events
    volume(d, 3500, 1500, 0.04 * factor)
    assert len(d.events) == 1
    event = d.events[0]
    assert event.kind == "volume" and event.direction == direction
    assert event.start_ms == 3000 and event.end_ms == 5000
    assert event.baseline == pytest.approx(20 * math.log10(0.04))
    assert event.unit == "dBFS"


def test_volume_silence_and_transient_are_not_changes():
    d = detector()
    volume(d, 0, 3000, 0.04)
    volume(d, 3000, 400, 0.001)
    volume(d, 3400, 600, 0.04)
    volume(d, 4000, 5000, 0, False)
    assert not d.events


@pytest.mark.parametrize("count,direction", [(30, "up"), (10, "down")])
def test_pace_uses_final_voiced_time_not_wall_clock(count, direction):
    d = detector()
    for at in (0, 2000, 4000):
        d.observe_pace(at, at + 2000, 20, 2000)
    d.observe_pace(6000, 9000, count, 2000)
    assert len(d.events) == 1
    event = d.events[0]
    assert (event.kind, event.direction, event.unit) == ("pace", direction, "syllables/min")
    assert event.baseline == 600
    assert event.value == count * 30


def test_short_or_unrecognized_answers_do_not_build_pace_baseline():
    d = detector()
    for at in range(0, 20000, 100):
        d.observe_pace(at, at + 100, 1, 100)
        d.observe_pace(at, at + 100, 0, 100)
    d.observe_pace(20000, 22000, 100, 2000)
    assert not d.events


def test_pace_transient_and_gaps_do_not_count_as_sustained_change():
    d = detector()
    for at in (0, 2000, 4000):
        d.observe_pace(at, at + 2000, 20, 2000)
    d.observe_pace(6000, 7000, 20, 1000)
    d.observe_pace(10000, 11000, 20, 1000)
    assert not d.events


def test_baseline_expires_and_storage_is_bounded():
    d = detector()
    volume(d, 0, 3000, 0.04)
    volume(d, 40000, 1000, 0.16)
    assert not d.events
    for at in range(41000, 41000 + 700000, 1000):
        volume(d, at, 1000, 0.04 if (at // 1000) % 2 else 0.16)
    assert 0 < len(d.events) <= 256
    assert all(
        set(asdict(e)) == {"kind", "direction", "start_ms", "end_ms", "baseline", "value", "unit"}
        for e in d.events
    )


def test_long_volume_shift_uses_recent_baseline_for_reversal():
    d = detector()
    volume(d, 0, 3000, 0.04)
    volume(d, 3000, 35000, 0.16)
    volume(d, 38000, 2000, 0.08)
    assert d.events[-1].direction == "down"
    assert d.events[-1].start_ms == 38000
    assert d.events[-1].baseline == pytest.approx(20 * math.log10(0.16))


def test_long_pace_shift_uses_recent_baseline_for_reversal():
    d = detector()
    for at in (0, 2000, 4000):
        d.observe_pace(at, at + 2000, 20, 2000)
    for at in range(6000, 42000, 2000):
        d.observe_pace(at, at + 2000, 30, 2000)
    d.observe_pace(42000, 44000, 20, 2000)
    assert d.events[-1].direction == "down"
    assert d.events[-1].start_ms == 42000
    assert d.events[-1].baseline == 900


def test_segmenter_observer_reuses_the_same_vad_decision():
    observed, calls = [], []

    def vad(pcm):
        calls.append(pcm)
        return True

    segmenter = SpeechSegmenter(is_speech=vad, observe_frame=lambda *args: observed.append(args))
    from uuid import uuid4

    segmenter.feed(
        MediaPayload(uuid4(), 1234, struct.pack("<h", 3276) * 320, format="pcm16", sample_count=320)
    )
    assert len(calls) == len(observed) == 1
    assert observed[0][:2] == (1234, 1254)
    assert observed[0][2] == pytest.approx(3276 / 32768)
    assert observed[0][3] is True


@pytest.mark.asyncio
async def test_detector_runs_in_pipeline_but_is_not_exposed():
    class Speech:
        async def infer(self, media):
            return AIResult("speech_rate", media.timestamp_ms, "info", "ok", {}, "네", True)

    p = pipeline(Speech())
    p.segmenter = SpeechSegmenter(
        is_speech=lambda _: True, observe_frame=p.speech_changes.observe_audio
    )
    observed = []
    p.subscribe("test", lambda event: collect(observed, event))
    await p.start()
    try:
        for seq, amplitude in enumerate([1000] * 6 + [6000] * 2):
            await p.audio_queue.put(
                MediaPayload(
                    p.session_id,
                    p.audio_origin_ms + seq * 500,
                    struct.pack("<h", amplitude) * 8000,
                    start_sample=seq * 8000,
                    format="pcm16",
                )
            )
            await p.audio_queue.join()
        assert p.speech_changes.events
    finally:
        report = await p.stop()
    exported = json.dumps([report, p.metrics(), [e.model_dump(mode="json") for e in observed]])
    assert "dBFS" not in exported and "speech_changes" not in exported
    assert "volume" not in exported


async def collect(events, event):
    events.append(event)


@pytest.mark.asyncio
async def test_rejected_transcript_never_reaches_counts_or_alignment():
    class Speech:
        async def infer(self, media):
            return AIResult(
                "speech_rate",
                media.timestamp_ms,
                "info",
                "uncertain",
                {"recognition_status": "rejected", "rejection_reason": "TRANSCRIPT_TOO_LONG"},
                None,
                False,
            )

    p = pipeline(Speech())
    p.update_analysis_settings({"script": "음 저는 개발자입니다.", "time_limit_seconds": 30})
    events = []
    p.subscribe("test", lambda event: collect(events, event))
    await p.start()
    await p.audio_queue.put(
        MediaPayload(
            p.session_id,
            p.audio_origin_ms,
            struct.pack("<h", 1000) * 8000 + bytes(16000),
            format="pcm16",
        )
    )
    report = await p.stop()
    assert report["transcript"] is None and report["average_syllables_per_minute"] is None
    assert report["filler_word_counts"] is None and report["incomplete"]
    assert not p.speech_window.items and not p.speech_changes.events
    assert not any(e.event in {"transcript.final", "script.progress"} for e in events)


@pytest.mark.asyncio
async def test_pipeline_pace_detection_is_internal_and_ignores_duplicate_finals():
    p = pipeline(object())
    p.phase = "running"
    events = []
    p.subscribe("test", lambda event: collect(events, event))
    final = None
    for seq, count in enumerate([20, 20, 20, 30]):
        final = AIResult(
            "speech_rate",
            seq * 2000,
            "info",
            "ok",
            {
                "start_ms": seq * 2000,
                "end_ms": (seq + 1) * 2000,
                "voiced_ms": 2000,
                "syllable_count": count,
                "utterance_id": f"u{seq}",
            },
            "가" * count,
            True,
        )
        await p._handle_result(final)
    assert len(p.speech_changes.events) == 1
    event = p.speech_changes.events[0]
    assert event.kind == "pace" and event.direction == "up"
    await p._handle_result(final)
    assert len(p.speech_changes.events) == 1
    exported = json.dumps([p.metrics(), [e.model_dump(mode="json") for e in events]])
    assert "syllables/min" not in exported and "speech_changes" not in exported
