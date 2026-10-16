"""Native subprocess fixture: only model factories are replaced, never the IPC."""

import asyncio
import os
import signal
import sys
import time
from dataclasses import asdict

from app.ai.base import AIResult, InferenceGate, MediaPayload
from app.core.config import Settings


class EchoModel:
    def __init__(self, modality: str) -> None:
        self.modality = modality
        self.gate = InferenceGate()

    async def infer(self, media: MediaPayload) -> AIResult:
        return await self.gate.run_once(lambda: self.echo(media))

    def echo(self, media: MediaPayload) -> AIResult:
        if media.payload == b"crash":
            os._exit(17)
        if media.payload == b"error":
            raise RuntimeError("PRIVATE_MEDIA_AND_EXCEPTION")
        if media.payload == b"slow":
            time.sleep(0.5)
        if media.payload == b"hang":
            time.sleep(60)
        fields = asdict(media)
        fields["session_id"] = str(media.session_id)
        fields["payload"] = media.payload.hex()
        return AIResult(
            self.modality if self.modality == "gaze" else "speech_rate",
            media.timestamp_ms,
            "warning",
            "검증 결과",
            {"pid": os.getpid(), "media": fields, "nested": [None, True, 1.25]},
            "발화 내용",
            True,
            23,
        )

    def close(self) -> None:
        self.gate.close()


def gaze_factory(settings: Settings) -> EchoModel:
    if "--load-fail" in sys.argv:
        raise RuntimeError("PRIVATE_LOAD_EXCEPTION")
    if "--slow-load" in sys.argv:
        time.sleep(60)
    return EchoModel("gaze")


def speech_factory(settings: Settings) -> EchoModel:
    return EchoModel("speech")


async def fixture_run() -> None:
    from app.ai.realtime_worker import run

    await run(sys.argv[-1], gaze_factory=gaze_factory, speech_factory=speech_factory)
    if "--ignore-eof" in sys.argv:
        await asyncio.sleep(60)


def main() -> None:
    # Like the real entrypoint, EOF exits even if a native thread is still blocked.
    loop = asyncio.new_event_loop()
    if "--ignore-eof" in sys.argv:
        signal.signal(signal.SIGTERM, signal.SIG_IGN)
    try:
        loop.run_until_complete(fixture_run())
    finally:
        loop.close()
        os._exit(0)


if __name__ == "__main__":
    main()
