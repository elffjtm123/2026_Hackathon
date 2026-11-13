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
from aiortc.mediastreams import MediaStreamError
from anyio import CancelScope
from av import AudioResampler

from app.ai.base import MediaPayload
from app.core.config import Settings
from app.core.errors import AppError
from app.realtime.pipeline import SessionPipeline

logger = logging.getLogger(__name__)
CONNECT_TIMEOUT_SECONDS = 30


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
        peers = self.connections.setdefault(session_id, set())
        # One client must not be able to allocate unlimited peer connections.
        if len(peers) >= self.settings.max_connections_per_session:
            raise AppError("TOO_MANY_CONNECTIONS", "동시 연결 수가 한도를 초과했습니다.", 429)
        pc = RTCPeerConnection(self._configuration())
        peers.add(pc)
        subscriber_id = f"webrtc-{uuid4()}"
        connect_timeout: asyncio.Task[None] | None = None

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
                self._track(
                    asyncio.create_task(
                        self._consume_video(track, pipeline), name=f"webrtc-video-{session_id}"
                    )
                )
            elif getattr(track, "kind", None) == "audio":
                self._track(
                    asyncio.create_task(
                        self._consume_audio(track, pipeline), name=f"webrtc-audio-{session_id}"
                    )
                )

        @pc.on("connectionstatechange")
        async def on_connectionstatechange() -> None:
            if pc.connectionState in {"connected", "failed", "closed", "disconnected"}:
                if connect_timeout is not None and connect_timeout is not asyncio.current_task():
                    connect_timeout.cancel()
            if pc.connectionState in {"failed", "closed", "disconnected"}:
                pipeline.unsubscribe(subscriber_id)
                peers = self.connections.get(session_id, set())
                unplanned = pc in peers
                peers.discard(pc)
                await pc.close()
                if unplanned and not self.connections.get(session_id) and not pipeline.subscribers:
                    pipeline.incomplete = True
                    await pipeline.stop()

        try:
            await pc.setRemoteDescription(RTCSessionDescription(sdp=sdp, type=offer_type))
            answer = await pc.createAnswer()
            await pc.setLocalDescription(answer)
            if pc.localDescription is None:
                raise RuntimeError("WebRTC answer was not created")

            async def expire_unconnected() -> None:
                nonlocal connect_timeout
                await asyncio.sleep(CONNECT_TIMEOUT_SECONDS)
                if pc.connectionState in {"new", "connecting"}:
                    connect_timeout = None
                    await pc.close()

            connect_timeout = asyncio.create_task(
                expire_unconnected(), name=f"webrtc-connect-{session_id}"
            )
            self._track(connect_timeout)
            return pc.localDescription
        except BaseException:
            with CancelScope(shield=True):
                pipeline.unsubscribe(subscriber_id)
                await pc.close()
                self.connections.get(session_id, set()).discard(pc)
            raise

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
        origin_ms: int | None = None
        sequence = pipeline.media_sequences["pcm16"]
        sample = pipeline.next_audio_sample

        async def send(payload: bytes) -> None:
            nonlocal sequence, sample
            sequence += 1
            await pipeline.accept_media(
                MediaPayload(
                    pipeline.session_id,
                    int(origin_ms or 0) + sample * 1000 // 16000,
                    payload,
                    sequence,
                    sample,
                    len(payload) // 2,
                    "pcm16",
                )
            )
            sample += len(payload) // 2

        try:
            while True:
                frame = await track.recv()  # type: ignore[attr-defined]
                if pipeline.phase != "running":
                    continue
                if origin_ms is None:
                    origin_ms = pipeline.elapsed_ms() - sample * 1000 // 16000
                # Resampling is local and bounded; raw audio is discarded after enqueueing.
                for resampled in resampler.resample(frame):
                    sample_bytes = bytes(resampled.planes[0])[: resampled.samples * 2]
                    buffer.extend(sample_bytes)
                    while len(buffer) >= chunk_size:
                        payload = bytes(buffer[:chunk_size])
                        del buffer[:chunk_size]
                        await send(payload)
        except asyncio.CancelledError:
            raise
        except MediaStreamError:
            pass
        except Exception:
            pipeline.incomplete = True
            await pipeline.emit_error("AUDIO_TRACK_FAILED", "음성 스트림 처리에 실패했습니다.")
        finally:
            if origin_ms is not None and pipeline.accepting and pipeline.phase == "running":
                try:
                    for resampled in resampler.resample(None):
                        buffer.extend(bytes(resampled.planes[0])[: resampled.samples * 2])
                    while buffer:
                        payload = bytes(buffer[:chunk_size])
                        del buffer[:chunk_size]
                        await send(payload)
                    await asyncio.wait_for(
                        pipeline.audio_queue.put(
                            MediaPayload(
                                pipeline.session_id, pipeline.elapsed_ms(), b"", format="flush"
                            )
                        ),
                        timeout=self.settings.audio_queue_wait_seconds,
                    )
                except Exception:
                    pipeline.incomplete = True
                    await pipeline.emit_error(
                        "AUDIO_TAIL_FAILED", "마지막 음성을 전달하지 못했습니다."
                    )

    async def close_session(self, session_id: UUID) -> None:
        connections = self.connections.pop(session_id, set())
        await asyncio.gather(*(pc.close() for pc in connections), return_exceptions=True)
        tasks = [task for task in self.tasks if task.get_name().endswith(str(session_id))]
        if tasks:
            _, pending = await asyncio.wait(tasks, timeout=2)
            for task in pending:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)

    async def close(self) -> None:
        await asyncio.gather(
            *(self.close_session(session_id) for session_id in list(self.connections)),
            return_exceptions=True,
        )
        for task in self.tasks:
            task.cancel()
        await asyncio.gather(*self.tasks, return_exceptions=True)
        self.tasks.clear()
