import asyncio
import importlib.util
import io
import json
import re
import time
from typing import Any

from app.ai.base import AIResult, MediaPayload


def active_speech_duration(
    audio: Any,
    sample_rate: int,
    threshold: float,
    frame_ms: int = 30,
) -> float:
    import numpy as np

    if sample_rate <= 0 or len(audio) == 0:
        return 0.0
    frame_size = max(1, round(sample_rate * frame_ms / 1000))
    active_samples = 0
    for start in range(0, len(audio), frame_size):
        frame = audio[start : start + frame_size]
        if len(frame) == 0:
            continue
        rms = float(np.sqrt(np.mean(np.square(frame))))
        if rms >= threshold:
            active_samples += len(frame)
    if active_samples == 0:
        return 0.0
    return max(0.5, active_samples / sample_rate)


def _decode_text_payload(payload: bytes) -> tuple[str, float | None] | None:
    try:
        raw = payload.decode("utf-8").strip()
    except UnicodeDecodeError:
        return None
    if any(ord(char) < 32 and char not in "\t\n\r" for char in raw):
        return None
    try:
        data: Any = json.loads(raw)
    except json.JSONDecodeError:
        return (raw, None) if raw else None
    if not isinstance(data, dict):
        return raw, None
    text = str(data.get("text", "")).strip()
    duration_ms = data.get("duration_ms")
    duration_sec = (
        max(0.5, float(duration_ms) / 1000)
        if isinstance(duration_ms, int | float)
        else None
    )
    return text, duration_sec


class LocalQwenSpeechAdapter:
    def __init__(
        self,
        model_name: str = "Qwen/Qwen3-ASR-0.6B",
        device: str = "auto",
        context: str = "",
        silence_rms_threshold: float = 0.003,
    ) -> None:
        if importlib.util.find_spec("qwen_asr") is None:
            raise RuntimeError("qwen-asr package is not installed")

        import numpy as np
        import soundfile as sf
        import torch
        from qwen_asr import Qwen3ASRModel

        from stt import FillerWordAnalyzer, SpeechRateAnalyzer

        resolved_device = (
            "mps" if device == "auto" and torch.backends.mps.is_available() else device
        )
        if resolved_device == "auto":
            resolved_device = "cpu"
        dtype = torch.float16 if resolved_device == "mps" else torch.float32

        self.np = np
        self.sf = sf
        self.context = context
        self.silence_rms_threshold = silence_rms_threshold
        self.stt = Qwen3ASRModel.from_pretrained(
            model_name,
            device_map=resolved_device,
            dtype=dtype,
            max_inference_batch_size=1,
            max_new_tokens=128,
        )
        self.rate = SpeechRateAnalyzer()
        self.filler = FillerWordAnalyzer()

    async def infer(self, media: MediaPayload) -> AIResult:
        started = time.perf_counter()
        return await asyncio.to_thread(self._infer_sync, media, started)

    def _infer_sync(self, media: MediaPayload, started: float) -> AIResult:
        text_payload = _decode_text_payload(media.payload)
        if text_payload is not None and not media.payload.startswith(b"RIFF"):
            transcript, duration = text_payload
            duration = duration or max(1.0, len(re.findall(r"[가-힣]", transcript)) / 5)
            return self._analyze_result(media, transcript, duration, started)

        if media.payload.startswith(b"RIFF"):
            audio, sample_rate = self.sf.read(
                io.BytesIO(media.payload), dtype="float32", always_2d=False
            )
            if audio.ndim > 1:
                audio = audio.mean(axis=1)
        else:
            sample_rate = 16_000
            audio = self.np.frombuffer(media.payload, dtype="<i2").astype(self.np.float32)
            audio /= 32768.0

        duration = len(audio) / sample_rate
        rms = float(self.np.sqrt(self.np.mean(self.np.square(audio)))) if len(audio) else 0.0
        if duration < 0.5 or rms < self.silence_rms_threshold:
            return self._analyze_result(media, "", duration, started, rms=rms)

        result = self.stt.transcribe(
            audio=(audio, sample_rate),
            context=self.context,
            language="Korean",
        )[0]
        speech_duration = active_speech_duration(
            audio, sample_rate, self.silence_rms_threshold
        )
        return self._analyze_result(
            media, result.text, speech_duration, started, rms=rms
        )

    def _analyze_result(
        self,
        media: MediaPayload,
        transcript: str,
        duration: float,
        started: float,
        *,
        rms: float | None = None,
    ) -> AIResult:
        transcript = transcript.strip()
        speech_rate = self.rate.analyze(transcript, duration)
        fillers = self.filler.analyze(transcript)
        filler_counts = dict(fillers.get("counts", {}))
        level = "warning" if speech_rate.get("level") in {"FAST", "SLOW"} else "info"

        return AIResult(
            source="speech_rate",
            timestamp_ms=media.timestamp_ms,
            level=level,
            message=(
                str(speech_rate.get("feedback", "발화 분석이 완료되었습니다."))
                if transcript
                else "음성이 감지되지 않았습니다."
            ),
            metrics={
                "syllables_per_minute": float(speech_rate.get("cpm", 0) or 0),
                "filler_words": [
                    {"word": word, "count": count} for word, count in filler_counts.items()
                ],
                "duration_sec": duration,
                "rms": rms,
            },
            transcript=transcript or None,
            is_final=True,
            latency_ms=int((time.perf_counter() - started) * 1000),
        )


def create_local_qwen_speech_adapter(
    model_name: str = "Qwen/Qwen3-ASR-0.6B",
    device: str = "auto",
    context: str = "",
    silence_rms_threshold: float = 0.003,
) -> LocalQwenSpeechAdapter:
    return LocalQwenSpeechAdapter(model_name, device, context, silence_rms_threshold)
