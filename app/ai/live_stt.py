"""Candidate engines reuse the service's current audio and transcript safety checks."""

from pathlib import Path
from typing import Any

from app.ai.base import InferenceGate
from app.ai.experimental_stt import create_engine
from app.ai.local_stt import LocalQwenSpeechAdapter


class _EngineTranscriber:
    def __init__(self, engine: Any) -> None:
        self.engine = engine

    def transcribe(self, *, audio: tuple[Any, int], language: str) -> str:
        samples, sample_rate = audio
        if sample_rate != 16000:
            raise ValueError("Live model comparison requires 16kHz audio")
        return self.engine.transcribe(samples)


class LiveCandidateSpeechAdapter(LocalQwenSpeechAdapter):
    def __init__(self, model_id: str, root: Path, settings: Any) -> None:
        import numpy as np
        import soundfile as sf

        self.np, self.sf = np, sf
        self.device = "cpu"
        self.silence_rms_threshold = settings.stt_silence_rms_threshold
        self.engine = create_engine(model_id, root, settings.stt_experiment_threads, "")
        self.stt = _EngineTranscriber(self.engine)
        self.gate = InferenceGate()

    def close(self) -> None:
        self.gate.close()
        self.engine.close()
