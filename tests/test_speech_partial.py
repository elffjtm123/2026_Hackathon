"""Live `transcript.partial` previews are display-only and never delay or alter finals."""

import asyncio
import struct
from uuid import uuid4

import pytest

from app.ai.base import AIResult, MediaPayload
from app.core.config import Settings
from app.modules.speech.segments import SpeechSegmenter
from app.realtime.experiment_recorder import ExperimentRecorder
from app.realtime.pipeline import SessionPipeline
from app.realtime.state import SessionStateStore

VOICED_200MS = struct.pack("<h", 1000) * 3200
QUIET_200MS = b"\0\0" * 3200


def pipeline(speech, **settings):
    result = SessionPipeline(
        uuid4(),
        Settings(_env_file=None),
        SessionStateStore(None),
        object(),
        speech,
        {"gaze_enabled": False, "pronunciation_enabled": False, **settings},
    )
    result.segmenter = SpeechSegmenter(is_speech=lambda pcm: struct.unpack_from("<h", pcm)[0] > 0)
    return result


class Recorder:
    def __init__(self, p):
        self.events = []
        p.subscribe("test", self.collect)

    async def collect(self, event):
        self.events.append(event)

    def named(self, name):
        return [e.data for e in self.events if e.event == name]


async def feed(p, chunks, *, start_chunk=0, pause=0.01):
    """Stream 200 ms packets in real order, letting background work run between them."""
    for offset, pcm in enumerate(chunks):
        index = start_chunk + offset
        await p.audio_queue.put(
            MediaPayload(
                p.session_id,
                p.audio_origin_ms + index * 200,
                pcm,
                start_sample=index * 3200,
                format="pcm16",
            )
        )
        await p.audio_queue.join()
        await asyncio.sleep(pause)


def duration_text(media):
    return AIResult(
        "speech_rate", media.timestamp_ms, "info", "ok", {}, f"길이{len(media.payload) // 32}", True
    )


@pytest.mark.asyncio
async def test_partials_preview_speech_but_never_reach_metrics_or_report():
    class Speech:
        async def infer(self, media):
            return duration_text(media)

    p = pipeline(Speech(), script="길이 소개합니다.", time_limit_seconds=30)
    seen = Recorder(p)
    await p.start()
    try:
        await feed(p, [VOICED_200MS] * 20 + [QUIET_200MS] * 3)
        await asyncio.wait_for(p.speech_queue.join(), 1)
    finally:
        report = await p.stop()

    partials = seen.named("transcript.partial")
    finals = seen.named("transcript.final")
    assert len(partials) >= 2
    assert {x["utterance_id"] for x in partials} == {"u1"}
    assert all(x["start_ms"] == p.audio_origin_ms for x in partials)
    ends = [x["end_ms"] for x in partials]
    assert ends == sorted(ends) and ends[0] - p.audio_origin_ms >= 1500
    assert all(x["text"] == f"길이{x['end_ms'] - x['start_ms']}" for x in partials)
    assert [(x["utterance_id"], x["start_ms"], x["end_ms"], x["voiced_ms"]) for x in finals] == [
        ("u1", p.audio_origin_ms, p.audio_origin_ms + 4100, 4000)
    ]
    # Partials precede their final and are not fed to any analysis.
    names = [e.event for e in seen.events if e.event.startswith("transcript.")]
    assert names[-1] == "transcript.final" and set(names[:-1]) == {"transcript.partial"}
    transcripts = [x["transcript"] for x in seen.named("feedback") if x.get("transcript")]
    assert transcripts == ["길이4100"]
    assert len(seen.named("script.progress")) == 1
    assert report["transcript"] == "길이4100"
    assert p.aggregator.voiced_ms == 4000


@pytest.mark.asyncio
async def test_partial_is_skipped_while_stt_is_busy_and_not_queued():
    release, entered = asyncio.Event(), asyncio.Event()
    calls = []

    class Speech:
        async def infer(self, media):
            calls.append(media)
            if len(calls) == 1:
                entered.set()
                await release.wait()
            return duration_text(media)

    p = pipeline(Speech())
    seen = Recorder(p)
    await p.start()
    try:
        # u1: short utterance whose final inference blocks the model.
        await feed(p, [VOICED_200MS] * 2 + [QUIET_200MS] * 3)
        await asyncio.wait_for(entered.wait(), 0.5)
        # u2: 3 s of continuous speech while u1 is still being transcribed.
        await feed(p, [VOICED_200MS] * 15, start_chunk=5)
        assert len(calls) == 1
        assert seen.named("transcript.partial") == []
        release.set()
        await asyncio.wait_for(p.speech_queue.join(), 0.5)
        # Skipped previews are not replayed once the model is free.
        await asyncio.sleep(0.02)
        assert len(calls) == 1  # Only u1's final; no backlog of u2 previews.
        await feed(p, [VOICED_200MS] * 8, start_chunk=20)
        assert [x["utterance_id"] for x in seen.named("transcript.partial")] == ["u2"]
    finally:
        release.set()
        await p.stop()
    assert [x["utterance_id"] for x in seen.named("transcript.final")] == ["u1", "u2"]


@pytest.mark.asyncio
async def test_partial_arriving_after_its_utterance_is_cut_is_dropped():
    release, entered = asyncio.Event(), asyncio.Event()
    calls = []

    class Speech:
        async def infer(self, media):
            calls.append(media)
            if len(calls) == 1:  # The first call is the preview of the running utterance.
                entered.set()
                await release.wait()
            return duration_text(media)

    p = pipeline(Speech())
    seen = Recorder(p)
    await p.start()
    try:
        await feed(p, [VOICED_200MS] * 9)
        await asyncio.wait_for(entered.wait(), 0.5)
        await feed(p, [QUIET_200MS] * 3, start_chunk=9)  # Endpoint cuts u1 meanwhile.
        release.set()
        await asyncio.wait_for(p.speech_queue.join(), 0.5)
    finally:
        release.set()
        await p.stop()
    assert seen.named("transcript.partial") == []
    finals = seen.named("transcript.final")
    assert [(x["utterance_id"], x["text"]) for x in finals] == [("u1", "길이1900")]
    assert len(calls) == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["experiment", "feedback_off"])
async def test_no_partials_for_experiment_or_hidden_transcripts(mode):
    calls = []

    class Speech:
        async def infer(self, media):
            calls.append(media)
            return duration_text(media)

    p = pipeline(Speech())
    if mode == "experiment":
        p.experiment = ExperimentRecorder({})
    else:
        p.analysis_settings.update(speech_rate_enabled=False, filler_words_enabled=False)
    seen = Recorder(p)
    await p.start()
    try:
        await feed(p, [VOICED_200MS] * 12 + [QUIET_200MS] * 3)
        await asyncio.wait_for(p.speech_queue.join(), 1)
    finally:
        await p.stop()
    assert seen.named("transcript.partial") == []
    assert len(calls) == 1
