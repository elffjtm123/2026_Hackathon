import io
import wave
from uuid import uuid4

import pytest

from app.ai.base import MediaPayload
from app.ai.mock import MockSpeechAdapter


@pytest.mark.asyncio
async def test_mock_stt_does_not_display_wav_bytes_as_transcript() -> None:
    output = io.BytesIO()
    with wave.open(output, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(16_000)
        wav.writeframes(b"\x00\x00" * 16_000)

    result = await MockSpeechAdapter().infer(MediaPayload(uuid4(), 1000, output.getvalue()))

    assert result.transcript is None
    assert "Mock" in result.message
