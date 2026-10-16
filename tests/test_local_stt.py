import io
import time
import wave
from uuid import uuid4

import numpy as np
import pytest
import soundfile as sf

from app.ai.base import MediaPayload
from app.ai.local_stt import (
    LocalQwenSpeechAdapter,
    active_speech_duration,
)


def test_active_speech_duration_excludes_silence() -> None:
    silence = np.zeros(16_000, dtype=np.float32)
    speech = np.full(16_000, 0.1, dtype=np.float32)
    audio = np.concatenate([silence, speech, silence])

    duration = active_speech_duration(audio, 16_000, 0.003)

    assert 0.9 <= duration <= 1.1


@pytest.mark.parametrize("wav", [False, True])
def test_silent_audio_skips_qwen_inference(wav: bool) -> None:
    class FailIfCalled:
        def transcribe(self, **_: object) -> object:
            raise AssertionError("silent audio must not reach Qwen")

    class EmptyAnalyzer:
        def analyze(self, *_: object) -> dict[str, object]:
            return {"cpm": 0, "level": "UNKNOWN", "counts": {}}

    adapter = LocalQwenSpeechAdapter.__new__(LocalQwenSpeechAdapter)
    adapter.np = np
    adapter.sf = sf
    adapter.silence_rms_threshold = 0.003
    adapter.stt = FailIfCalled()
    adapter.rate = EmptyAnalyzer()
    adapter.filler = EmptyAnalyzer()

    audio = np.zeros(16_000, dtype="<i2").tobytes()
    if wav:
        output = io.BytesIO()
        with wave.open(output, "wb") as stream:
            stream.setnchannels(1)
            stream.setsampwidth(2)
            stream.setframerate(16_000)
            stream.writeframes(audio)
        audio = output.getvalue()
    payload = MediaPayload(uuid4(), 0, audio)
    result = adapter._infer_sync(payload, time.perf_counter())

    assert result.transcript is None
    assert result.metrics["rms"] == 0.0


def test_low_level_microphone_noise_does_not_reach_qwen() -> None:
    from stt import FillerWordAnalyzer, SpeechRateAnalyzer

    class FailIfCalled:
        def transcribe(self, **_: object) -> object:
            raise AssertionError("microphone noise must not reach Qwen")

    adapter = LocalQwenSpeechAdapter.__new__(LocalQwenSpeechAdapter)
    adapter.np = np
    adapter.silence_rms_threshold = 0.003
    adapter.stt = FailIfCalled()
    adapter.rate = SpeechRateAnalyzer()
    adapter.filler = FillerWordAnalyzer()

    noise = np.random.default_rng(7).normal(0, 0.005, 32_000)
    payload = MediaPayload(uuid4(), 1000, (noise * 32767).astype("<i2").tobytes())
    result = adapter._infer_sync(payload, time.perf_counter())

    assert result.transcript is None
    assert result.level == "info"
    assert result.metrics["syllables_per_minute"] is None
    assert result.metrics["pace"] == "unknown"
    assert result.metrics["rms"] > adapter.silence_rms_threshold


def test_text_cannot_bypass_qwen_inference(monkeypatch: pytest.MonkeyPatch) -> None:
    from stt import FillerWordAnalyzer, SpeechRateAnalyzer

    class FailingModel:
        def transcribe(self, **_: object) -> object:
            raise RuntimeError("model inference failed")

    adapter = LocalQwenSpeechAdapter.__new__(LocalQwenSpeechAdapter)
    adapter.np = np
    adapter.silence_rms_threshold = 0.003
    adapter.stt = FailingModel()
    adapter.rate = SpeechRateAnalyzer()
    adapter.filler = FillerWordAnalyzer()
    monkeypatch.setattr("app.ai.local_stt.has_speech", lambda *_: True)
    payload = b'{"text":"invented transcript","duration_ms":2000}'
    # Also valid, long PCM bytes: the former text shortcut must not take precedence.
    payload = payload.ljust(16_000, b" ")

    with pytest.raises(RuntimeError, match="model inference failed"):
        adapter._infer_sync(MediaPayload(uuid4(), 0, payload), time.perf_counter())


def test_confirmed_100ms_segment_is_transcribed_without_second_vad_gate():
    class Model:
        def transcribe(self, **kwargs):
            assert len(kwargs["audio"][0]) == 1600
            return "네"

    adapter = LocalQwenSpeechAdapter.__new__(LocalQwenSpeechAdapter)
    adapter.np, adapter.sf = np, sf
    adapter.silence_rms_threshold = 0.003
    adapter.stt = Model()
    media = MediaPayload(
        uuid4(),
        0,
        np.full(1600, 1000, dtype="<i2").tobytes(),
        format="pcm16",
        utterance_id="u1",
        end_ms=100,
        voiced_ms=100,
    )
    result = adapter._infer_sync(media, time.perf_counter())
    assert result.transcript == "네"
    assert result.metrics["voiced_ms"] == 100


def confirmed_adapter(text="네"):
    class Model:
        calls = 0

        def transcribe(self, **kwargs):
            assert "context" not in kwargs
            self.calls += 1
            return text

    adapter = LocalQwenSpeechAdapter.__new__(LocalQwenSpeechAdapter)
    adapter.np, adapter.sf = np, sf
    adapter.silence_rms_threshold = 0.003
    adapter.stt = Model()
    return adapter


@pytest.mark.parametrize("amplitude", [0, 1])
def test_confirmed_silence_still_skips_inference(amplitude):
    adapter = confirmed_adapter()
    media = MediaPayload(
        uuid4(),
        0,
        np.full(4800, amplitude, dtype="<i2").tobytes(),
        format="pcm16",
        utterance_id="u1",
        voiced_ms=100,
        end_ms=300,
    )
    result = adapter._infer_sync(media, time.perf_counter())
    assert adapter.stt.calls == 0
    assert result.transcript is None
    assert result.metrics["recognition_status"] == "no_speech"
    assert result.metrics["voiced_ms"] == 0


@pytest.mark.parametrize("text", ["", " . 。!? … ", "가" * 100])
def test_nonlexical_and_runaway_transcripts_are_not_accepted(text):
    adapter = confirmed_adapter(text)
    media = MediaPayload(
        uuid4(),
        0,
        np.full(4800, 1000, dtype="<i2").tobytes(),
        format="pcm16",
        utterance_id="u1",
        voiced_ms=240,
        end_ms=300,
    )
    result = adapter._infer_sync(media, time.perf_counter())
    assert result.transcript is None
    assert result.metrics["recognition_status"] in {"unrecognized", "rejected"}
    assert result.metrics["voiced_ms"] == 0
    if text:
        assert text not in str(result.metrics)


@pytest.mark.parametrize("text", ["네", "이", "음 음 음", "네 네"])
def test_short_words_and_real_repetition_are_preserved(text):
    adapter = confirmed_adapter(text)
    media = MediaPayload(
        uuid4(),
        0,
        np.full(1600, 1000, dtype="<i2").tobytes(),
        format="pcm16",
        utterance_id="u1",
        voiced_ms=100,
        end_ms=100,
    )
    assert adapter._infer_sync(media, time.perf_counter()).transcript == text


def test_nonfinite_wav_does_not_reach_model():
    adapter = confirmed_adapter()
    output = io.BytesIO()
    sf.write(output, np.full(8000, np.nan), 16000, format="WAV", subtype="FLOAT")
    with pytest.raises(ValueError, match="INVALID_AUDIO"):
        adapter._infer_sync(MediaPayload(uuid4(), 0, output.getvalue()), time.perf_counter())
    assert adapter.stt.calls == 0


def test_padded_quiet_100ms_answer_is_not_mistaken_for_silence():
    from app.modules.speech.segments import SpeechSegmenter

    segmenter = SpeechSegmenter(is_speech=lambda pcm: np.frombuffer(pcm, dtype="<i2").max() > 0)
    pcm = bytes(6400) + np.full(1600, 131, dtype="<i2").tobytes() + bytes(16000)
    raw = MediaPayload(uuid4(), 0, pcm, format="pcm16")
    segment = segmenter.feed(raw)[0]
    assert segment.voiced_ms == 100
    adapter = confirmed_adapter()
    result = adapter._infer_sync(
        MediaPayload(
            raw.session_id,
            segment.start_ms,
            segment.pcm,
            format="pcm16",
            utterance_id=segment.utterance_id,
            voiced_ms=segment.voiced_ms,
            end_ms=segment.end_ms,
        ),
        time.perf_counter(),
    )
    assert result.metrics["rms"] < adapter.silence_rms_threshold
    assert result.transcript == "네"
    assert adapter.stt.calls == 1
