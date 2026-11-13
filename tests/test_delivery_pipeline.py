import asyncio
import json
import struct
import threading
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.ai.base import AIResult, MediaPayload
from app.modules.speech.segments import SpeechSegmenter
from app.realtime import pipeline as pipeline_module
from app.schemas.session import AnalysisSettings
from tests.test_speech_pipeline import pipeline

LOUD, QUIET = struct.pack("<h", 1000), b"\0\0"


def voiced_then_silence(voiced_samples=8000, silent_samples=8000):
    return LOUD * voiced_samples + QUIET * silent_samples


@pytest.fixture
def vad(monkeypatch):
    """The pipeline builds its own segmenter, so the real observe_frame wiring is exercised."""
    monkeypatch.setattr(
        pipeline_module,
        "SpeechSegmenter",
        lambda **kwargs: SpeechSegmenter(
            is_speech=lambda pcm: struct.unpack_from("<h", pcm)[0] > 0, **kwargs
        ),
    )


class Talker:
    def __init__(self, *texts):
        self.texts = list(texts)

    async def infer(self, media):
        text = self.texts.pop(0) if self.texts else "네"
        if text is None:
            return AIResult(
                "speech_rate",
                media.timestamp_ms,
                "info",
                "uncertain",
                {"recognition_status": "rejected"},
                None,
                False,
            )
        return AIResult("speech_rate", media.timestamp_ms, "info", "ok", {}, text, True)


class Recorder:
    def __init__(self, fail_on_utterance=False):
        self.fail_on_utterance = fail_on_utterance
        self.frames = 0
        self.calls = []

    def observe_frame(self, *args):
        self.frames += 1

    def observe_utterance(self, *args):
        self.calls.append(args)
        if self.fail_on_utterance:
            raise RuntimeError("boom")

    def report(self):
        return {"status": "observed"}

    def windows(self):
        return {"windows": []}


async def start_at(p, offset_s=25):
    """Start running with a session clock that is already past zero."""
    await p.prepare()
    p.started_monotonic -= offset_s
    await p.start_running()
    return p.audio_origin_ms


async def feed(p, *chunks):
    """Queue consecutive PCM chunks on the session clock and wait until they are processed."""
    sample = 0
    for pcm in chunks:
        await p.audio_queue.put(
            MediaPayload(
                p.session_id,
                p.audio_origin_ms + sample // 16,
                pcm,
                start_sample=sample,
                format="pcm16",
            )
        )
        sample += len(pcm) // 2
    await p.audio_queue.join()
    await p.speech_queue.join()


def delivery_pipeline(speech, **settings):
    p = pipeline(speech)
    p.segmenter = None
    p.update_analysis_settings(settings)
    return p


@pytest.mark.asyncio
async def test_frame_and_utterance_clocks_line_up_on_the_session_origin(vad):
    p = delivery_pipeline(Talker("음 안녕하세요 여러분"))
    origin = await start_at(p)
    assert origin >= 25_000
    await feed(p, voiced_then_silence())
    metrics = (await p.stop())["delivery_metrics"]
    first = metrics["windows"]["windows"][0]
    assert first["start_ms"] == origin
    # Frames were claimed by the utterance: all 500 ms voiced land in the first window.
    assert first["voiced_ms"] == 500
    assert first["syllables"] == 9 and first["disfluencies"] == 1
    sentence = metrics["report"]["sentences"][0]
    assert sentence["sentence_index"] == 0 and sentence["voiced_ms"] == 500
    assert metrics["status"] == "unavailable"  # under a minute voiced
    assert metrics["agc_on"] is None


@pytest.mark.asyncio
async def test_rejected_utterance_is_still_observed_with_zero_counts(vad):
    p = delivery_pipeline(Talker(None))
    await start_at(p)
    await feed(p, voiced_then_silence())
    report = await p.stop()
    sentence = report["delivery_metrics"]["report"]["sentences"][0]
    assert sentence["voiced_ms"] == 500 and sentence["syllables"] == 0
    assert report["delivery_metrics"]["windows"]["windows"][0]["disfluencies"] == 0
    assert report["transcript"] is None and report["incomplete"]


@pytest.mark.asyncio
async def test_toggle_off_creates_no_analyzer_and_reports_disabled(vad):
    p = delivery_pipeline(Talker("안녕하세요"), delivery_enabled=False)
    await start_at(p)
    assert p.delivery is None
    await feed(p, voiced_then_silence())
    report = await p.stop()
    assert report["delivery_metrics"] == {"status": "disabled"}
    assert report["transcript"] == "안녕하세요"


@pytest.mark.asyncio
async def test_analyzer_failure_marks_delivery_failed_and_the_worker_survives(vad):
    p = delivery_pipeline(Talker("첫째", "둘째"))
    await start_at(p)
    recorder = p.delivery = Recorder(fail_on_utterance=True)
    events = []

    async def collect(event):
        events.append(event)

    p.subscribe("test", collect)
    await feed(p, voiced_then_silence(), voiced_then_silence())
    report = await p.stop()
    finals = [e for e in events if e.event == "transcript.final"]
    assert [e.data["text"] for e in finals] == ["첫째", "둘째"]
    assert len(recorder.calls) == 1  # no further calls once failed
    assert report["delivery_metrics"]["status"] == "failed"
    assert report["delivery_metrics"]["report"] is None
    assert report["transcript"] == "첫째 둘째" and not report["incomplete"]


@pytest.mark.asyncio
async def test_frame_hook_failure_marks_delivery_failed(vad):
    p = delivery_pipeline(Talker("네"))
    await start_at(p)

    class Broken(Recorder):
        def observe_frame(self, *args):
            raise RuntimeError("boom")

    p.delivery = Broken()
    await feed(p, voiced_then_silence())
    assert (await p.stop())["delivery_metrics"]["status"] == "failed"


@pytest.mark.asyncio
async def test_utterance_arguments_carry_segment_metadata(vad):
    p = delivery_pipeline(Talker("음 어 저는 저는 개발자입니다"))
    origin = await start_at(p)
    recorder = p.delivery = Recorder()
    await feed(p, voiced_then_silence())
    await p.stop()
    ((start, end, pcm, cut, sentence_index, syllables, disfluencies),) = recorder.calls
    assert start == origin and end > start and len(pcm) == (end - start) * 32
    assert (cut, sentence_index, syllables, disfluencies) == ("endpoint", 0, 12, 3)
    assert recorder.frames > 0


@pytest.mark.asyncio
async def test_flushed_tail_reports_its_cut_reason(vad):
    p = delivery_pipeline(Talker("네"))
    await start_at(p)
    recorder = p.delivery = Recorder()
    await feed(p, LOUD * 8000)
    await p.stop()
    assert recorder.calls[0][3] == "flush"


@pytest.mark.asyncio
async def test_sentence_index_never_goes_backwards():
    p = delivery_pipeline(Talker("가", "나", "다"))
    indexes = iter([1, 0, None])

    def update(text, ms, is_final):
        index = next(indexes)
        return {
            "current_sentence_index": index,
            "progress_ratio": 0.5,
            "alignment_status": "uncertain",
            "pace_delta_ms": None,
            "pace_status": "on_time",
        }

    p.script_sync = SimpleNamespace(update=update)
    p.segmenter = SpeechSegmenter(
        is_speech=lambda pcm: struct.unpack_from("<h", pcm)[0] > 0,
        observe_frame=p._observe_delivery_frame,
    )
    await start_at(p)
    p.script_sync = SimpleNamespace(update=update)
    recorder = p.delivery = Recorder()
    await feed(p, voiced_then_silence(), voiced_then_silence(), voiced_then_silence())
    await p.stop()
    assert [call[4] for call in recorder.calls] == [1, 1, 1]


@pytest.mark.asyncio
async def test_no_script_means_sentence_zero(vad):
    p = delivery_pipeline(Talker("네", "네"))
    await start_at(p)
    recorder = p.delivery = Recorder()
    await feed(p, voiced_then_silence(), voiced_then_silence())
    await p.stop()
    assert [call[4] for call in recorder.calls] == [0, 0]


@pytest.mark.asyncio
async def test_nothing_delivery_related_is_emitted_live(vad):
    p = delivery_pipeline(Talker("음 안녕하세요"))
    events = []

    async def collect(event):
        events.append(event)

    p.subscribe("test", collect)
    await start_at(p)
    await feed(p, voiced_then_silence())
    live = json.dumps([p.metrics(), [e.model_dump(mode="json") for e in events]])
    report = await p.stop()
    completed = next(e for e in events if e.event == "session.completed")
    exported = json.dumps(
        [live, completed.model_dump(mode="json"), [e.model_dump(mode="json") for e in events]]
    )
    for leak in ("dBFS", "dbfs", "delivery", "loudness", "pvq", "windows"):
        assert leak not in exported
    assert "delivery_metrics" in report


def test_segmenter_observer_reuses_the_same_vad_decision():
    observed, calls = [], []

    def vad_fn(pcm):
        calls.append(pcm)
        return True

    segmenter = SpeechSegmenter(is_speech=vad_fn, observe_frame=lambda *args: observed.append(args))
    segmenter.feed(
        MediaPayload(uuid4(), 1234, struct.pack("<h", 3276) * 320, format="pcm16", sample_count=320)
    )
    assert len(calls) == len(observed) == 1
    assert observed[0][:2] == (1234, 1254)
    assert observed[0][2] == pytest.approx(3276 / 32768)
    assert observed[0][3] is True


@pytest.mark.asyncio
async def test_rejected_transcript_never_reaches_counts_or_alignment(vad):
    p = delivery_pipeline(Talker(None))
    p.update_analysis_settings({"script": "음 저는 개발자입니다.", "time_limit_seconds": 30})
    events = []

    async def collect(event):
        events.append(event)

    p.subscribe("test", collect)
    await start_at(p)
    await feed(p, voiced_then_silence())
    report = await p.stop()
    assert report["transcript"] is None and report["average_syllables_per_minute"] is None
    assert report["filler_word_counts"] is None and report["incomplete"]
    assert not p.speech_window.items
    assert not any(e.event in {"transcript.final", "script.progress"} for e in events)


def test_delivery_enabled_defaults_on_and_accepts_camel_case():
    assert AnalysisSettings().delivery_enabled is True
    assert AnalysisSettings.model_validate({"deliveryEnabled": False}).delivery_enabled is False
    assert AnalysisSettings.model_validate({"delivery_enabled": False}).delivery_enabled is False


@pytest.mark.parametrize(
    "raw,expected",
    [
        ({"autoGainControl": True}, True),
        ({"autoGainControl": False}, False),
        ({"autoGainControl": "true"}, None),
        ({"autoGainControl": 1}, None),
        ({"autoGainControl": None}, None),
        ({}, None),
        ("autoGainControl", None),
        (None, None),
    ],
)
def test_agc_flag_accepts_only_booleans(raw, expected):
    p = delivery_pipeline(object())
    p.set_audio_settings(raw)
    assert p.agc_on is expected


@pytest.mark.asyncio
async def test_agc_flag_is_reported_in_delivery_metrics(vad):
    p = delivery_pipeline(Talker("네"))
    p.set_audio_settings({"autoGainControl": True})
    await start_at(p)
    assert (await p.stop())["delivery_metrics"]["agc_on"] is True


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "toggles",
    [
        {"speech_rate_enabled": False, "filler_words_enabled": False},
        {"speech_rate_enabled": False},
        {"filler_words_enabled": False},
    ],
)
async def test_delivery_counts_do_not_depend_on_the_analysis_toggles(vad, toggles):
    p = delivery_pipeline(Talker("음 안녕하세요 여러분"), **toggles)
    await start_at(p)
    await feed(p, voiced_then_silence())
    report = await p.stop()
    first = report["delivery_metrics"]["windows"]["windows"][0]
    assert first["syllables"] == 9 and first["disfluencies"] == 1
    if not toggles.get("speech_rate_enabled", True) and not toggles.get(
        "filler_words_enabled", True
    ):
        assert report["transcript"] is None  # no speech feedback was produced


@pytest.mark.asyncio
async def test_drain_timeout_with_an_utterance_in_flight_marks_delivery_failed(vad):
    release = threading.Event()
    started = threading.Event()

    class Blocking(Recorder):
        def observe_utterance(self, *args):
            started.set()
            release.wait(5)

    p = delivery_pipeline(Talker("안녕하세요"))
    p.settings.pipeline_grace_seconds = 0.05
    await start_at(p)
    p.delivery = Blocking()
    await p.audio_queue.put(
        MediaPayload(
            p.session_id, p.audio_origin_ms, voiced_then_silence(), start_sample=0, format="pcm16"
        )
    )
    try:
        assert await asyncio.to_thread(started.wait, 5)
        report = await p.stop()
    finally:
        release.set()
    assert report["incomplete"]
    assert report["delivery_metrics"]["status"] == "failed"
    assert report["delivery_metrics"]["report"] is None


@pytest.mark.asyncio
async def test_speech_waiting_notice_is_not_sent_when_both_speech_toggles_are_off(vad):
    p = delivery_pipeline(Talker(), speech_rate_enabled=False, filler_words_enabled=False)
    events = []

    async def collect(event):
        events.append(event.event)

    p.subscribe("x", collect)
    await start_at(p)
    before = p.aggregator.snapshot()
    await feed(p, QUIET * 16000 * 3)
    await p.stop()
    assert "feedback" not in events
    assert p.aggregator.snapshot() == before


@pytest.mark.asyncio
async def test_delivery_only_branch_does_not_transcribe_legacy_chunks(vad):
    class Counting(Talker):
        calls = 0

        async def infer(self, media):
            type(self).calls += 1
            return await super().infer(media)

    p = delivery_pipeline(Counting(), speech_rate_enabled=False, filler_words_enabled=False)
    await start_at(p)
    await p.speech_queue.put(MediaPayload(p.session_id, 0, b"legacy-audio"))
    await p.speech_queue.join()
    await p.stop()
    assert Counting.calls == 0
