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
    adapter.context = "한국어 개발자 면접입니다."
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
    adapter.context = ""
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
    from types import SimpleNamespace

    class Model:
        def transcribe(self, **kwargs):
            assert len(kwargs["audio"][0]) == 1600
            return [SimpleNamespace(text="네")]

    adapter = LocalQwenSpeechAdapter.__new__(LocalQwenSpeechAdapter)
    adapter.np, adapter.sf = np, sf
    adapter.context = ""
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
