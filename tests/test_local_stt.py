import time
from uuid import uuid4

import numpy as np

from app.ai.base import MediaPayload
from app.ai.local_stt import LocalQwenSpeechAdapter, _decode_text_payload


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
