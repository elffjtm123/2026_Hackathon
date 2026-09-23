import time
from uuid import uuid4

import numpy as np

from app.ai.base import MediaPayload
from app.ai.local_stt import (
    LocalQwenSpeechAdapter,
    _decode_text_payload,
    active_speech_duration,
)


def test_active_speech_duration_excludes_silence() -> None:
    silence = np.zeros(16_000, dtype=np.float32)
    speech = np.full(16_000, 0.1, dtype=np.float32)
    audio = np.concatenate([silence, speech, silence])

    duration = active_speech_duration(audio, 16_000, 0.003)

    assert 0.9 <= duration <= 1.1


def test_pcm_silence_skips_qwen_inference() -> None:
    class FailIfCalled:
        def transcribe(self, **_: object) -> object:
            raise AssertionError("silent audio must not reach Qwen")

    class EmptyAnalyzer:
        def analyze(self, *_: object) -> dict[str, object]:
            return {"cpm": 0, "level": "UNKNOWN", "counts": {}}

    adapter = LocalQwenSpeechAdapter.__new__(LocalQwenSpeechAdapter)
    adapter.np = np
    adapter.silence_rms_threshold = 0.003
    adapter.stt = FailIfCalled()
    adapter.rate = EmptyAnalyzer()
    adapter.filler = EmptyAnalyzer()

    payload = MediaPayload(uuid4(), 0, np.zeros(16_000, dtype="<i2").tobytes())
    result = adapter._infer_sync(payload, time.perf_counter())

    assert _decode_text_payload(payload.payload) is None
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
    assert result.metrics["syllables_per_minute"] == 0
    assert result.metrics["rms"] > adapter.silence_rms_threshold
