"""Test-only model doubles. Never imported by the service."""

import asyncio
import json
import re
from collections import Counter
from typing import Any

from app.ai.base import AIResult, MediaPayload
from app.realtime.events import ModuleStatus

FILLER_PATTERN = re.compile(r"(?<![가-힣])(어|음|그|저기|그러니까)(?![가-힣])")


class FakeProcessProxy:
    def __init__(self):
        self.adapter = None

    def __getattr__(self, name):
        if self.adapter is None:
            raise AttributeError(name)
        return getattr(self.adapter, name)

    async def infer(self, media):
        if self.adapter is None:
            raise RuntimeError("MODEL_UNAVAILABLE")
        return await self.adapter.infer(media)


class FakeRealtimeModelProcess:
    """Test-only lifecycle double; factories are invoked on start, never constructor."""

    def __init__(self, settings):
        self.settings = settings
        self.gaze, self.speech = FakeProcessProxy(), FakeProcessProxy()
        self.process = None
        self.modules = {
            "gaze": ModuleStatus(
                provider="uniface", model="MediaPipe Face Landmarker + MobileGaze", status="idle"
            ),
            "speech": ModuleStatus(provider="qwen3_asr", model=settings.stt_model, status="idle"),
        }

    async def start(self):
        from app.main import create_local_gaze_adapter, create_local_qwen_speech_adapter

        factories = {
            "gaze": lambda: create_local_gaze_adapter(self.settings),
            "speech": lambda: create_local_qwen_speech_adapter(
                self.settings.stt_model,
                self.settings.stt_device,
                self.settings.stt_context,
                self.settings.stt_silence_rms_threshold,
                self.settings.stt_library_path,
            ),
        }
        for name, factory in factories.items():
            proxy = getattr(self, name)
            try:
                proxy.adapter = factory()
                reason = getattr(proxy.adapter, "reason", None)
                self.modules[name].status = "unavailable" if reason else "ready"
                self.modules[name].reason = reason
                self.modules[name].device = getattr(proxy.adapter, "device", None)
            except Exception as exc:
                self.modules[name].status = "unavailable"
                self.modules[name].reason = f"MODEL_LOAD_FAILED: {name} ({type(exc).__name__})"
        if any(module.status == "unavailable" for module in self.modules.values()):
            raise ValueError("MODEL_UNAVAILABLE_OR_BUSY")

    async def stop(self):
        self.gaze.adapter = self.speech.adapter = None
        for module in self.modules.values():
            if module.status != "unavailable":
                module.status = "idle"
            module.device = None


def _decode_transcript_payload(payload: bytes) -> tuple[str, float | None]:
    if payload.startswith(b"RIFF"):
        return "", None
    try:
        raw = payload.decode("utf-8").strip()
    except UnicodeDecodeError:
        return "", None
    if any(ord(char) < 32 and char not in "\t\n\r" for char in raw):
        return "", None
    try:
        data: Any = json.loads(raw)
    except json.JSONDecodeError:
        return raw, None
    if not isinstance(data, dict):
        return raw, None
    text = str(data.get("text", "")).strip()
    duration_ms = data.get("duration_ms")
    duration_sec = (
        max(0.5, float(duration_ms) / 1000) if isinstance(duration_ms, int | float) else None
    )
    return text, duration_sec


class FakeGazeAdapter:
    async def infer(self, media: MediaPayload) -> AIResult:
        await asyncio.sleep(0.01)
        away = (media.timestamp_ms // 1000) % 7 == 6
        return AIResult(
            source="gaze",
            timestamp_ms=media.timestamp_ms,
            level="warning" if away else "info",
            message="시선을 카메라 중앙으로 돌려주세요." if away else "시선 처리가 안정적입니다.",
            metrics={
                "face_detected": True,
                "head_pose": {
                    "yaw": -20.0 if away else 1.2,
                    "pitch": -1.1,
                    "roll": 0.0,
                },
                "gaze_direction": "left" if away else "center",
                "gaze_angles": {"yaw": -20.0 if away else 1.2, "pitch": -1.1},
                "quality_flags": [],
                "face_detection_confidence": None,
                "direction": "left" if away else "center",
                "attention_state": "away" if away else "camera",
                "away": away,
                "quality": 0.91,
                "confidence": 0.91,
                "calibrated": False,
                "yaw": -12.0 if away else 1.2,
                "pitch": -1.1,
            },
            latency_ms=10,
        )


class FakeSpeechAdapter:
    async def infer(self, media: MediaPayload) -> AIResult:
        await asyncio.sleep(0.02)
        text, duration_sec = (
            ("", None) if media.format == "pcm16" else _decode_transcript_payload(media.payload)
        )
        fillers = Counter(FILLER_PATTERN.findall(text))
        syllables = len(re.findall(r"[가-힣]", text))
        estimated_duration_sec = duration_sec or max(1.0, syllables / 5)
        speech_rate = syllables / estimated_duration_sec * 60 if estimated_duration_sec else 0
        level = "warning" if speech_rate > 360 else "info"
        return AIResult(
            source="speech_rate",
            timestamp_ms=media.timestamp_ms,
            level=level,
            message=(
                "Test-only speech fixture: no transcript"
                if not text
                else "발화 속도가 조금 빠릅니다."
                if level == "warning"
                else "발화 속도가 적절합니다."
            ),
            metrics={
                "syllables_per_minute": speech_rate,
                "filler_words": [{"word": word, "count": count} for word, count in fillers.items()],
                "duration_sec": round(estimated_duration_sec, 2),
                "avg_logprob": -0.35 if text else -1.0,
                "no_speech_prob": 0.1 if text else 1.0,
            },
            transcript=text or None,
            is_final=True,
            latency_ms=20,
        )
