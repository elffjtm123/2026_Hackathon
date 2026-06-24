import asyncio
import io
import logging
import time
from uuid import UUID, uuid4

from aiortc import (
    RTCConfiguration,
    RTCIceServer,
    RTCPeerConnection,
    RTCSessionDescription,
)
from av import AudioResampler

from app.core.config import Settings
from app.realtime.pipeline import SessionPipeline

logger = logging.getLogger(__name__)


class WebRTCManager:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.connections: dict[UUID, set[RTCPeerConnection]] = {}
        self.tasks: set[asyncio.Task[None]] = set()

    def _configuration(self) -> RTCConfiguration:
        servers: list[RTCIceServer] = []
        if self.settings.turn_url:
            servers.append(
                RTCIceServer(
                    urls=self.settings.turn_url,
                    username=self.settings.turn_username,
                    credential=self.settings.turn_credential,
                )
            )
        return RTCConfiguration(iceServers=servers)

    async def create_answer(
        self, session_id: UUID, sdp: str, offer_type: str, pipeline: SessionPipeline
    ) -> RTCSessionDescription:
        pc = RTCPeerConnection(self._configuration())
        self.connections.setdefault(session_id, set()).add(pc)
        subscriber_id = f"webrtc-{uuid4()}"

        @pc.on("datachannel")
        def on_datachannel(channel: object) -> None:
            if getattr(channel, "label", None) != "feedback":
                return

            async def send_event(event: object) -> None:
                if getattr(channel, "readyState", None) == "open":
                    channel.send(event.model_dump_json())  # type: ignore[attr-defined]

            pipeline.subscribe(subscriber_id, send_event)

            @channel.on("message")  # type: ignore[attr-defined]
            def on_message(message: object) -> None:
                if message == "ping" and getattr(channel, "readyState", None) == "open":
                    channel.send("pong")  # type: ignore[attr-defined]

        @pc.on("track")
        def on_track(track: object) -> None:
            if getattr(track, "kind", None) == "video":
                self._track(asyncio.create_task(self._consume_video(track, pipeline)))
            elif getattr(track, "kind", None) == "audio":
                self._track(asyncio.create_task(self._consume_audio(track, pipeline)))

        @pc.on("connectionstatechange")
        async def on_connectionstatechange() -> None:
            if pc.connectionState in {"failed", "closed", "disconnected"}:
                pipeline.unsubscribe(subscriber_id)
                await pc.close()
                self.connections.get(session_id, set()).discard(pc)

        await pc.setRemoteDescription(RTCSessionDescription(sdp=sdp, type=offer_type))
        answer = await pc.createAnswer()
        await pc.setLocalDescription(answer)
        if pc.localDescription is None:
            raise RuntimeError("WebRTC answer was not created")
        return pc.localDescription

    def _track(self, task: asyncio.Task[None]) -> None:
        self.tasks.add(task)
        task.add_done_callback(self.tasks.discard)

    async def _consume_video(self, track: object, pipeline: SessionPipeline) -> None:
        interval = 1 / self.settings.video_sample_fps
        last_sample = 0.0
        try:
            while True:
                frame = await track.recv()  # type: ignore[attr-defined]
                now = time.monotonic()
                if now - last_sample < interval:
                    continue
                last_sample = now
                output = io.BytesIO()
                frame.to_image().save(output, format="JPEG", quality=80)
                await pipeline.push_video(pipeline.elapsed_ms(), output.getvalue())
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.info("video_track_ended", extra={"session_id": pipeline.session_id})

    async def _consume_audio(self, track: object, pipeline: SessionPipeline) -> None:
        resampler = AudioResampler(format="s16", layout="mono", rate=16_000)
        chunk_size = int(16_000 * 2 * self.settings.audio_chunk_ms / 1_000)
        buffer = bytearray()
        try:
            while True:
                frame = await track.recv()  # type: ignore[attr-defined]
                # Resampling is local and bounded; raw audio is discarded after enqueueing.
                for resampled in resampler.resample(frame):
                    sample_bytes = bytes(resampled.planes[0])[: resampled.samples * 2]
                    buffer.extend(sample_bytes)
                    while len(buffer) >= chunk_size:
                        payload = bytes(buffer[:chunk_size])
                        del buffer[:chunk_size]
                        await pipeline.push_audio(pipeline.elapsed_ms(), payload)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.info("audio_track_ended", extra={"session_id": pipeline.session_id})

    async def close_session(self, session_id: UUID) -> None:
        connections = self.connections.pop(session_id, set())
        await asyncio.gather(*(pc.close() for pc in connections), return_exceptions=True)

    async def close(self) -> None:
        await asyncio.gather(
            *(self.close_session(session_id) for session_id in list(self.connections)),
            return_exceptions=True,
        )
        for task in self.tasks:
            task.cancel()
        await asyncio.gather(*self.tasks, return_exceptions=True)
        self.tasks.clear()
