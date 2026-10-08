import asyncio
from fractions import Fraction
from types import SimpleNamespace
from uuid import uuid4

import pytest
from aiortc.mediastreams import MediaStreamError
from av import AudioFrame

from app.core.config import Settings
from app.realtime.webrtc import WebRTCManager


@pytest.mark.asyncio
async def test_webrtc_pcm_timestamps_and_resampler_tail():
    frames = []
    for index in range(3):
        frame = AudioFrame(format="s16", layout="stereo", samples=4800)
        frame.sample_rate = 48000
        frame.pts = index * 4800
        frame.time_base = Fraction(1, 48000)
        frame.planes[0].update(b"\x10\x00" * 9600)
        frames.append(frame)

    class Track:
        async def recv(self):
            if not frames:
                raise MediaStreamError
            return frames.pop(0)

    accepted = []
    legacy = []

    async def accept(media):
        accepted.append(media)

    async def push(*args):
        legacy.append(args)

    pipeline = SimpleNamespace(
        session_id=uuid4(),
        phase="running",
        accepting=True,
        elapsed_ms=lambda: 100,
        accept_media=accept,
        push_audio=push,
        audio_queue=asyncio.Queue(),
        incomplete=False,
        media_sequences={"pcm16": 0},
        next_audio_sample=0,
    )
    await WebRTCManager(Settings(audio_chunk_ms=200))._consume_audio(Track(), pipeline)
    assert not legacy
    assert [media.sample_count for media in accepted] == [3200, 1600]
    assert [media.timestamp_ms for media in accepted] == [100, 300]
    assert [media.start_sample for media in accepted] == [0, 3200]
    assert [media.sequence for media in accepted] == [1, 2]
    assert all(media.format == "pcm16" for media in accepted)
    assert pipeline.audio_queue.get_nowait().format == "flush"
