import asyncio
import time
from typing import Any

import httpx

from app.ai.base import AIResult, MediaPayload
from app.core.config import Settings


class AIServiceError(RuntimeError):
    pass


class _HTTPAdapter:
    path: str

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.client = httpx.AsyncClient(
            base_url=settings.ai_base_url,
            timeout=httpx.Timeout(
                connect=settings.ai_connect_timeout_seconds,
                read=settings.ai_read_timeout_seconds,
                write=settings.ai_read_timeout_seconds,
                pool=settings.ai_connect_timeout_seconds,
            ),
        )

    async def _request(self, media: MediaPayload, content_type: str) -> dict[str, Any]:
        last_error: Exception | None = None
        for attempt in range(self.settings.ai_max_retries + 1):
            try:
                response = await self.client.post(
                    self.path,
                    data={"session_id": str(media.session_id), "timestamp_ms": media.timestamp_ms},
                    files={"file": ("media", media.payload, content_type)},
                )
                response.raise_for_status()
                return response.json()
            except (httpx.TimeoutException, httpx.NetworkError, httpx.HTTPStatusError) as exc:
                last_error = exc
                retryable = (
                    not isinstance(exc, httpx.HTTPStatusError) or exc.response.status_code >= 500
                )
                if not retryable or attempt == self.settings.ai_max_retries:
                    break
                await asyncio.sleep(0.1 * (2**attempt))
        raise AIServiceError("AI service request failed") from last_error


class HTTPGazeAdapter(_HTTPAdapter):
    path = "/v1/gaze/infer"

    async def infer(self, media: MediaPayload) -> AIResult:
        started = time.perf_counter()
        data = await self._request(media, "image/jpeg")
        away = bool(data["away"])
        return AIResult(
            source="gaze",
            timestamp_ms=int(data.get("timestamp_ms", media.timestamp_ms)),
            level="warning" if away else "info",
            message="시선을 카메라 중앙으로 돌려주세요." if away else "시선 처리가 안정적입니다.",
            metrics={key: data[key] for key in ("direction", "away", "confidence", "yaw", "pitch")},
            latency_ms=int((time.perf_counter() - started) * 1000),
        )


class HTTPSpeechAdapter(_HTTPAdapter):
    path = "/v1/speech/infer"

    async def infer(self, media: MediaPayload) -> AIResult:
        started = time.perf_counter()
        data = await self._request(media, "audio/L16;rate=16000;channels=1")
        rate = float(data.get("syllables_per_minute", 0))
        return AIResult(
            source="speech_rate",
            timestamp_ms=int(data.get("timestamp_ms", media.timestamp_ms)),
            level="warning" if rate > 360 else "info",
            message="발화 속도가 조금 빠릅니다." if rate > 360 else "발화 속도가 적절합니다.",
            metrics={
                "syllables_per_minute": rate,
                "filler_words": data.get("filler_words", []),
            },
            transcript=data.get("transcript"),
            is_final=bool(data.get("is_final", False)),
            latency_ms=int((time.perf_counter() - started) * 1000),
        )
