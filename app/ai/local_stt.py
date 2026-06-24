import asyncio
import importlib.util
import json
import re
import tempfile
import time
from pathlib import Path
from typing import Any

from app.ai.base import AIResult, MediaPayload


def _decode_text_payload(payload: bytes) -> tuple[str, float | None]:
    raw = payload.decode("utf-8", errors="ignore").strip()
    try:
        data: Any = json.loads(raw)
    except json.JSONDecodeError:
        return raw, None
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


class LocalWhisperSpeechAdapter:
    def __init__(self, model_size: str = "small") -> None:
        if importlib.util.find_spec("faster_whisper") is None and importlib.util.find_spec(
            "whisper"
        ) is None:
            raise RuntimeError("Whisper STT package is not installed")

        from stt import ClarityAnalyzer, FillerWordAnalyzer, SpeechRateAnalyzer, STTEngine

        self.stt = STTEngine(model_size=model_size, language="ko")
        self.rate = SpeechRateAnalyzer()
        self.filler = FillerWordAnalyzer()
        self.clarity = ClarityAnalyzer()

    async def infer(self, media: MediaPayload) -> AIResult:
        started = time.perf_counter()
        return await asyncio.to_thread(self._infer_sync, media, started)

    def _infer_sync(self, media: MediaPayload, started: float) -> AIResult:
        if not media.payload.startswith(b"RIFF"):
            transcript, duration = _decode_text_payload(media.payload)
            duration = duration or max(1.0, len(re.findall(r"[가-힣]", transcript)) / 5)
            stt_result = {
                "transcript": transcript,
                "duration": duration,
                "avg_logprob": -0.35 if transcript else -1.0,
                "no_speech_prob": 0.1 if transcript else 1.0,
            }
            return self._analyze_result(media, stt_result, started)

        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as temp_file:
            temp_file.write(media.payload)
            temp_path = Path(temp_file.name)

        try:
            stt_result = self.stt.transcribe_file(str(temp_path))
        finally:
            temp_path.unlink(missing_ok=True)

        return self._analyze_result(media, stt_result, started)

    def _analyze_result(
        self, media: MediaPayload, stt_result: dict[str, Any], started: float
    ) -> AIResult:
        transcript = str(stt_result.get("transcript", "")).strip()
        duration = float(stt_result.get("duration", 0) or 0)
        speech_rate = self.rate.analyze(transcript, duration)
        fillers = self.filler.analyze(transcript)
        clarity = self.clarity.analyze(transcript, stt_result)
        syllables_per_minute = float(speech_rate.get("cpm", 0) or 0)
        filler_counts = dict(fillers.get("counts", {}))
        level = "warning" if speech_rate.get("level") in {"FAST", "SLOW"} else "info"

        return AIResult(
            source="speech_rate",
            timestamp_ms=media.timestamp_ms,
            level=level,
            message=str(speech_rate.get("feedback", "발화 분석이 완료되었습니다.")),
            metrics={
                "syllables_per_minute": syllables_per_minute,
                "filler_words": [
                    {"word": word, "count": count} for word, count in filler_counts.items()
                ],
                "duration_sec": duration,
                "avg_logprob": stt_result.get("avg_logprob"),
                "no_speech_prob": stt_result.get("no_speech_prob"),
                "clarity": clarity,
            },
            transcript=transcript or None,
            is_final=True,
            latency_ms=int((time.perf_counter() - started) * 1000),
        )


def create_local_whisper_speech_adapter(model_size: str = "small") -> LocalWhisperSpeechAdapter:
    return LocalWhisperSpeechAdapter(model_size=model_size)
