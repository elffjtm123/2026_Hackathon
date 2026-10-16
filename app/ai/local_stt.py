import io
import math
import time
from typing import Any

from app.ai.base import AIResult, InferenceGate, MediaPayload
from app.ai.native_stt import QwenGGUF

DEFAULT_STT_MODEL = ".models/Qwen3-ASR-0.6B-Q8_0.gguf"
DEFAULT_STT_LIBRARY = ".models/speech/libspeech.dylib"


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


def has_speech(audio: Any, sample_rate: int) -> bool:
    import numpy as np
    import webrtcvad

    if sample_rate <= 0 or len(audio) == 0:
        return False
    if sample_rate not in {8_000, 16_000, 32_000, 48_000}:
        positions = np.arange(0, len(audio), sample_rate / 16_000)
        audio = np.interp(positions, np.arange(len(audio)), audio)
        sample_rate = 16_000

    pcm = np.clip(np.asarray(audio) * 32768, -32768, 32767).astype("<i2").tobytes()
    frame_bytes = sample_rate // 50 * 2  # 20 ms, mono PCM16
    vad = webrtcvad.Vad(2)
    voiced_frames = sum(
        vad.is_speech(pcm[offset : offset + frame_bytes], sample_rate)
        for offset in range(0, len(pcm) - frame_bytes + 1, frame_bytes)
    )
    return voiced_frames >= 8  # 160 ms rejects short noise bursts


class LocalQwenSpeechAdapter:
    def __init__(
        self,
        model_name: str = DEFAULT_STT_MODEL,
        device: str = "auto",
        silence_rms_threshold: float = 0.003,
        library_path: str = DEFAULT_STT_LIBRARY,
    ) -> None:
        import numpy as np
        import soundfile as sf

        self.np = np
        self.sf = sf
        self.silence_rms_threshold = silence_rms_threshold
        self.stt = QwenGGUF(model_name, device, library_path)
        self.device = self.stt.device
        self.gate = InferenceGate()

    async def infer(self, media: MediaPayload) -> AIResult:
        started = time.perf_counter()
        return await self.gate.run_once(lambda: self._infer_sync(media, started))

    def close(self) -> None:
        self.gate.close()
        # A cancelled asyncio waiter may still have native inference using these weights.
        if self.gate.busy and self.gate.future is not None:
            self.gate.future.add_done_callback(lambda _: self.stt.close())
        else:
            self.stt.close()

    def _infer_sync(self, media: MediaPayload, started: float) -> AIResult:
        if media.format != "pcm16" and media.payload.startswith(b"RIFF"):
            audio, sample_rate = self.sf.read(
                io.BytesIO(media.payload), dtype="float32", always_2d=False
            )
            if audio.ndim > 1:
                audio = audio.mean(axis=1)
        else:
            sample_rate = 16_000
            audio = self.np.frombuffer(media.payload, dtype="<i2").astype(self.np.float32)
            audio /= 32768.0

        if not self.np.isfinite(audio).all():
            raise ValueError("INVALID_AUDIO")
        duration = len(audio) / sample_rate
        rms = float(self.np.sqrt(self.np.mean(self.np.square(audio)))) if len(audio) else 0.0
        confirmed = media.voiced_ms is not None
        if media.voiced_ms is not None and (
            media.format != "pcm16"
            or not media.utterance_id
            or not 0 < media.voiced_ms <= round(duration * 1000)
        ):
            raise ValueError("INVALID_CONFIRMED_SEGMENT")
        quiet = rms < self.silence_rms_threshold
        if media.voiced_ms is not None:
            # Check frame energy, not padded-segment RMS; never rerun VAD on short answers.
            frame_size = sample_rate // 50
            energetic_samples = sum(
                len(audio[offset : offset + frame_size])
                for offset in range(0, len(audio), frame_size)
                if float(self.np.mean(self.np.square(audio[offset : offset + frame_size])))
                >= self.silence_rms_threshold**2
            )
            quiet = energetic_samples * 1000 < min(media.voiced_ms, 100) * sample_rate
        if (
            not len(audio)
            or quiet
            or (
                not confirmed
                and (
                    (media.format != "pcm16" and duration < 0.5)
                    or not has_speech(audio, sample_rate)
                )
            )
        ):
            return self._analyze_result(media, "", 0, started, rms=rms, status="no_speech")

        result = self.stt.transcribe(audio=(audio, sample_rate), language="Korean").strip()
        speech_duration = (
            media.voiced_ms / 1000
            if media.voiced_ms is not None
            else active_speech_duration(audio, sample_rate, self.silence_rms_threshold)
        )
        characters = sum(character.isalnum() for character in result)
        if not characters:
            return self._analyze_result(media, "", 0, started, rms=rms, status="unrecognized")
        # shortcut: catches runaway length, not plausible hallucinations; tune with real speech.
        if characters > max(20, math.ceil(speech_duration * 20)):
            return self._analyze_result(
                media, "", 0, started, rms=rms, status="rejected", reason="TRANSCRIPT_TOO_LONG"
            )
        return self._analyze_result(media, result, speech_duration, started, rms=rms)

    def _analyze_result(
        self,
        media: MediaPayload,
        transcript: str,
        duration: float,
        started: float,
        *,
        rms: float | None = None,
        status: str = "recognized",
        reason: str | None = None,
    ) -> AIResult:
        transcript = transcript.strip()
        return AIResult(
            source="speech_rate",
            timestamp_ms=media.timestamp_ms,
            level="info",
            message=(
                "발화를 인식했습니다."
                if transcript
                else "음성 대기 중입니다."
                if status == "no_speech"
                else "음성을 명확히 인식하지 못했습니다."
            ),
            metrics={
                "pace": "unknown",
                "syllables_per_minute": None,
                "voiced_ms": round(duration * 1000),
                "filler_words": [],
                "duration_sec": duration,
                "rms": rms,
                "recognition_status": status,
                "rejection_reason": reason,
            },
            transcript=transcript or None,
            is_final=bool(transcript),
            latency_ms=int((time.perf_counter() - started) * 1000),
        )


def create_local_qwen_speech_adapter(
    model_name: str = DEFAULT_STT_MODEL,
    device: str = "auto",
    silence_rms_threshold: float = 0.003,
    library_path: str = DEFAULT_STT_LIBRARY,
) -> LocalQwenSpeechAdapter:
    return LocalQwenSpeechAdapter(model_name, device, silence_rms_threshold, library_path)
