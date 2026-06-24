import asyncio
import re
from collections import Counter

from app.ai.base import AIResult, MediaPayload

FILLER_PATTERN = re.compile(r"(?<![가-힣])(어|음|그|저기|그러니까)(?![가-힣])")


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
                "direction": "left" if away else "center",
                "away": away,
                "confidence": 0.91,
                "yaw": -12.0 if away else 1.2,
                "pitch": -1.1,
            },
            latency_ms=10,
        )


class MockSpeechAdapter:
    async def infer(self, media: MediaPayload) -> AIResult:
        await asyncio.sleep(0.02)
        text = media.payload.decode("utf-8", errors="ignore").strip()
        fillers = Counter(FILLER_PATTERN.findall(text))
        syllables = len(re.findall(r"[가-힣]", text))
        # Mock transcript chunks represent roughly one second of speech.
        speech_rate = syllables * 60
        level = "warning" if speech_rate > 360 else "info"
        return AIResult(
            source="speech_rate",
            timestamp_ms=media.timestamp_ms,
            level=level,
            message="발화 속도가 조금 빠릅니다."
            if level == "warning"
            else "발화 속도가 적절합니다.",
            metrics={
                "syllables_per_minute": speech_rate,
                "filler_words": [{"word": word, "count": count} for word, count in fillers.items()],
            },
            transcript=text or None,
            is_final=True,
            latency_ms=20,
        )
