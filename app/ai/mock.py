import asyncio
import json
import re
from collections import Counter
from typing import Any

from app.ai.base import AIResult, MediaPayload

FILLER_PATTERN = re.compile(r"(?<![가-힣])(어|음|그|저기|그러니까)(?![가-힣])")


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
        max(0.5, float(duration_ms) / 1000)
        if isinstance(duration_ms, int | float)
        else None
    )
    return text, duration_sec


class MockGazeAdapter:
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


class MockSpeechAdapter:
    async def infer(self, media: MediaPayload) -> AIResult:
        await asyncio.sleep(0.02)
        text, duration_sec = _decode_transcript_payload(media.payload)
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
                "Mock STT는 실제 음성을 받아쓰지 않습니다. STT_PROVIDER=qwen3_asr로 실행하세요."
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
