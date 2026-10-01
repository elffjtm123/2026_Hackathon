import asyncio
import hashlib
import logging
import time
from collections.abc import Awaitable, Callable
from dataclasses import replace
from typing import Any
from uuid import UUID

from app.ai.base import AIResult, GazeAdapter, MediaPayload, SpeechAdapter
from app.core.config import Settings
from app.modules.gaze.service import GazeStabilizer
from app.modules.pronunciation.service import estimate_stt_pronunciation_accuracy
from app.modules.script_sync.service import ScriptSyncService, analyze_script
from app.realtime.aggregator import FeedbackAggregator
from app.realtime.events import RealtimeEvent
from app.realtime.queues import DropOldestQueue
from app.realtime.state import SessionStateStore

Subscriber = Callable[[RealtimeEvent], Awaitable[None]]
logger = logging.getLogger(__name__)


class SessionPipeline:
    def __init__(
        self,
        session_id: UUID,
        settings: Settings,
        state_store: SessionStateStore,
        gaze: GazeAdapter,
        speech: SpeechAdapter,
        analysis_settings: dict[str, bool],
    ) -> None:
        self.session_id = session_id
        self.settings = settings
        self.state_store = state_store
        self.gaze = gaze
        self.speech = speech
        self.analysis_settings = analysis_settings
        self.video_queue: DropOldestQueue[MediaPayload] = DropOldestQueue(settings.video_queue_size)
        self.audio_queue: asyncio.Queue[MediaPayload] = asyncio.Queue(settings.audio_queue_size)
        self.aggregator = FeedbackAggregator()
        self.gaze_stabilizer = GazeStabilizer(calibration_frames=8)
        self.subscribers: dict[str, Subscriber] = {}
        self.tasks: list[asyncio.Task[None]] = []
        self.running = False
        self.accepting = False
        self.sequence = 0
        self.started_monotonic = time.monotonic()
        self._sequence_lock = asyncio.Lock()
        self._stop_lock = asyncio.Lock()
        self.completed_report: dict[str, Any] | None = None
        self.phase = "preparing"
        self.protocol = 1
        self.running_started_ms: int | None = None
        self.audio_origin_ms = 0
        self.incomplete = False
        self.media_sequences = {"jpeg": 0, "pcm16": 0}
        self.media_timestamps = {"jpeg": -1, "pcm16": -1}
        self.next_audio_sample = 0
        self._pcm_buffer = bytearray()
        self._pcm_start = 0
        self.audio_receipts: dict[int, bytes] = {}
        script = analysis_settings.get("script")
        time_limit = analysis_settings.get("time_limit_seconds")
        self.script_sync: ScriptSyncService | None = None
        if isinstance(script, str) and script and isinstance(time_limit, int) and time_limit > 0:
            self.script_sync = ScriptSyncService(analyze_script(script, time_limit))

    def update_analysis_settings(self, settings: dict[str, Any]) -> None:
        self.analysis_settings.update(settings)
        script = self.analysis_settings.get("script")
        time_limit = self.analysis_settings.get("time_limit_seconds")
        if isinstance(script, str) and script and isinstance(time_limit, int) and time_limit > 0:
            self.script_sync = ScriptSyncService(analyze_script(script, time_limit))

    async def start(self) -> None:
        await self.prepare()
        await self.start_running()

    async def prepare(self) -> None:
        if self.running:
            return
        for enabled, adapter in [
            (self.analysis_settings.get("gaze_enabled", True), self.gaze),
            (
                self.analysis_settings.get("speech_rate_enabled", True)
                or self.analysis_settings.get("filler_words_enabled", True),
                self.speech,
            ),
        ]:
            if enabled and (
                hasattr(adapter, "reason") or getattr(getattr(adapter, "gate", None), "busy", False)
            ):
                raise ValueError("MODEL_UNAVAILABLE_OR_BUSY")
        self.running = True
        self.started_monotonic = time.monotonic()
        self.tasks = [
            asyncio.create_task(self._video_worker(), name=f"video-{self.session_id}"),
            asyncio.create_task(self._audio_worker(), name=f"audio-{self.session_id}"),
        ]
        await self.state_store.set(self.session_id, {"status": "active", **self.metrics()})

    async def start_calibration(self) -> None:
        if self.phase not in {"preparing", "calibrating", "running"}:
            raise ValueError("INVALID_SESSION_STATE")
        self.gaze_stabilizer = GazeStabilizer(calibration_frames=8)
        self.gaze_stabilizer.begin_calibration(self.elapsed_ms())
        if self.phase == "running":
            return
        self.phase = "calibrating"
        self.accepting = True
        if not self.analysis_settings.get("gaze_enabled", True):
            await self.start_running()
        else:
            await self.emit("session.calibrating", self.elapsed_ms(), {})

    async def start_running(self) -> None:
        if self.phase == "running":
            return
        if self.phase not in {"preparing", "calibrating"}:
            raise ValueError("INVALID_SESSION_STATE")
        self.phase = "running"
        self.accepting = True
        self.running_started_ms = self.audio_origin_ms = self.elapsed_ms()
        await self.emit(
            "session.running" if self.protocol == 2 else "session.started",
            self.elapsed_ms(),
            {
                "running_started_ms": self.running_started_ms,
                "audio_origin_ms": self.audio_origin_ms,
            },
        )

    async def accept_media(self, media: MediaPayload) -> None:
        if not self.accepting or (media.format == "pcm16" and self.phase != "running"):
            raise ValueError("INVALID_SESSION_STATE")
        kind = media.format
        last = self.media_sequences[kind]
        receipt = hashlib.blake2s(
            media.payload
            + f"{media.timestamp_ms}:{media.start_sample}:{media.sample_count}".encode()
        ).digest()
        if kind == "pcm16" and media.sequence <= last:
            if self.audio_receipts.get(media.sequence) != receipt:
                self.incomplete = True
                raise ValueError("INVALID_AUDIO_REPLAY")
            await self.emit(
                "media.ack",
                self.elapsed_ms(),
                {"media_type": "audio", "accepted_sequence": media.sequence},
            )
            return
        if (
            media.timestamp_ms > self.elapsed_ms() + 1000
            or media.timestamp_ms < self.media_timestamps[kind]
        ):
            self.incomplete = True
            raise ValueError("INVALID_MEDIA_TIMESTAMP")
        if media.sequence <= last or (
            kind == "pcm16"
            and (media.sequence != last + 1 or media.start_sample != self.next_audio_sample)
        ):
            self.incomplete = True
            raise ValueError("MEDIA_SEQUENCE_GAP")
        if kind == "jpeg":
            self.video_queue.put_latest(media)
        else:
            try:
                await asyncio.wait_for(
                    self.audio_queue.put(media), self.settings.audio_queue_wait_seconds
                )
            except asyncio.TimeoutError as exc:
                self.incomplete = True
                raise ValueError("AUDIO_QUEUE_FULL") from exc
            self.next_audio_sample += media.sample_count
            self.audio_receipts[media.sequence] = receipt
            if len(self.audio_receipts) > 32:
                del self.audio_receipts[min(self.audio_receipts)]
        self.media_sequences[kind] = media.sequence
        self.media_timestamps[kind] = media.timestamp_ms
        if kind == "pcm16":
            await self.emit(
                "media.ack",
                self.elapsed_ms(),
                {"media_type": "audio", "accepted_sequence": media.sequence},
            )

    def subscribe(self, subscriber_id: str, callback: Subscriber) -> None:
        self.subscribers[subscriber_id] = callback

    def unsubscribe(self, subscriber_id: str) -> None:
        self.subscribers.pop(subscriber_id, None)

    async def push_video(self, timestamp_ms: int, payload: bytes) -> None:
        if not self.accepting:
            return
        self.video_queue.put_latest(MediaPayload(self.session_id, timestamp_ms, payload))

    async def push_audio(self, timestamp_ms: int, payload: bytes) -> bool:
        if not self.accepting or self.phase != "running":
            return False
        media = MediaPayload(self.session_id, timestamp_ms, payload)
        try:
            await asyncio.wait_for(
                self.audio_queue.put(media), timeout=self.settings.audio_queue_wait_seconds
            )
            return True
        except TimeoutError:
            await self.emit_error("AUDIO_QUEUE_FULL", "오디오 처리량이 한도를 초과했습니다.")
            self.incomplete = True
            return False

    async def stop(self) -> dict[str, Any]:
        async with self._stop_lock:
            if self.completed_report is not None:
                return self.completed_report

            self.accepting = False
            self.phase = "draining"
            incomplete = self.incomplete
            if self.running:
                if self.protocol == 2:
                    await self.emit("session.draining", self.elapsed_ms(), self.metrics())
                # Video is replaceable; accepted audio must be drained, including its tail.
                self.tasks[0].cancel()

                async def drain() -> None:
                    await self.audio_queue.put(
                        MediaPayload(self.session_id, self.elapsed_ms(), b"", format="flush")
                    )
                    await self.audio_queue.join()

                try:
                    await asyncio.wait_for(
                        drain(),
                        timeout=self.settings.pipeline_grace_seconds,
                    )
                except asyncio.TimeoutError:
                    incomplete = True
                    logger.warning(
                        "pipeline_grace_timeout",
                        extra={"session_id": self.session_id},
                    )
                for task in self.tasks:
                    task.cancel()
                await asyncio.gather(*self.tasks, return_exceptions=True)
                self.tasks.clear()
                self.running = False

            report = {**self.aggregator.report(), "incomplete": incomplete or self.incomplete}
            self._pcm_buffer.clear()
            self.audio_receipts.clear()
            for queue in [self.audio_queue, self.video_queue.queue]:
                while not queue.empty():
                    queue.get_nowait()
                    queue.task_done()
            self.phase = "completed"
            self.completed_report = report
            await self.state_store.set(
                self.session_id,
                {"status": "completed", **self.metrics()},
            )
            await self.emit("session.completed", self.elapsed_ms(), {"report": report})
            return report

    async def emit(
        self,
        event_name: str,
        timestamp_ms: int,
        data: dict[str, Any],
        *,
        module: str = "system",
        level: str = "info",
    ) -> RealtimeEvent:
        async with self._sequence_lock:
            self.sequence += 1
            event = RealtimeEvent(
                event=event_name,  # type: ignore[arg-type]
                version=self.protocol,
                session_id=self.session_id,
                sequence=self.sequence,
                timestamp_ms=max(0, timestamp_ms),
                module=module,  # type: ignore[arg-type]
                level=level,  # type: ignore[arg-type]
                data=data,
            )
            results = await asyncio.gather(
                *(callback(event) for callback in list(self.subscribers.values())),
                return_exceptions=True,
            )
        if any(isinstance(result, Exception) for result in results):
            logger.info("stale_realtime_subscriber", extra={"session_id": self.session_id})
        return event

    async def emit_error(self, code: str, message: str) -> None:
        await self.emit("error", self.elapsed_ms(), {"code": code, "message": message})

    async def _video_worker(self) -> None:
        while True:
            media = await self.video_queue.get()
            try:
                if self.analysis_settings.get("gaze_enabled", True):
                    stabilizer = self.gaze_stabilizer
                    if (
                        self.protocol == 2
                        and stabilizer.calibration_started_ms is not None
                        and media.timestamp_ms < stabilizer.calibration_started_ms
                    ):
                        continue
                    result = await self.gaze.infer(media)
                    if stabilizer is not self.gaze_stabilizer:
                        continue
                    if self.protocol == 2 and self.elapsed_ms() - media.timestamp_ms > 1500:
                        result = replace(
                            result,
                            metrics={
                                **result.metrics,
                                "quality": 0.0,
                                "quality_flags": [
                                    *result.metrics.get("quality_flags", []),
                                    "stale_observation",
                                ],
                            },
                        )
                    result = stabilizer.update(result)
                    if self.phase == "calibrating":
                        await self.emit(
                            "feedback",
                            result.timestamp_ms,
                            {
                                "source": result.source,
                                "message": result.message,
                                "metrics": result.metrics,
                                "level": result.level,
                            },
                            module="gaze",
                        )
                        if result.metrics.get("calibrated"):
                            await self.start_running()
                    elif self.phase == "running":
                        await self._handle_result(result)
            except asyncio.CancelledError:
                raise
            except Exception:
                self.incomplete = True
                logger.exception(
                    "gaze_inference_failed",
                    extra={"session_id": self.session_id, "error_code": "GAZE_AI_FAILED"},
                )
                await self.emit_error("GAZE_AI_UNAVAILABLE", "시선 분석이 일시적으로 지연됩니다.")
            finally:
                self.video_queue.task_done()

    async def _audio_worker(self) -> None:
        while True:
            media = await self.audio_queue.get()
            try:
                if media.format in {"pcm16", "flush"}:
                    if media.format == "pcm16":
                        if not self._pcm_buffer:
                            self._pcm_start = media.start_sample
                        self._pcm_buffer.extend(media.payload)
                    # ponytail: fixed 2s non-overlap chunks until S1 adds VAD segmentation.
                    if len(self._pcm_buffer) < 64000 and media.format != "flush":
                        continue
                    if not self._pcm_buffer:
                        continue
                    count = len(self._pcm_buffer) // 2
                    media = MediaPayload(
                        self.session_id,
                        self.audio_origin_ms + self._pcm_start * 1000 // 16000,
                        bytes(self._pcm_buffer),
                        start_sample=self._pcm_start,
                        sample_count=count,
                        format="pcm16",
                    )
                    self._pcm_buffer.clear()
                if self.analysis_settings.get(
                    "speech_rate_enabled", True
                ) or self.analysis_settings.get("filler_words_enabled", True):
                    result = await self.speech.infer(media)
                    await self._handle_result(result)
            except asyncio.CancelledError:
                raise
            except Exception:
                self.incomplete = True
                logger.exception(
                    "speech_inference_failed",
                    extra={"session_id": self.session_id, "error_code": "SPEECH_AI_FAILED"},
                )
                await self.emit_error(
                    "SPEECH_AI_UNAVAILABLE",
                    "음성 분석에 실패했습니다. 백엔드 로그와 STT 모델 설치 상태를 확인하세요.",
                )
            finally:
                self.audio_queue.task_done()
                if self.phase == "draining" and self.protocol == 2:
                    await self.emit("session.draining", self.elapsed_ms(), self.metrics())

    async def _handle_result(self, result: AIResult) -> None:
        if self.phase not in {"running", "draining"}:
            return
        self.aggregator.add(result)
        await self.state_store.set(self.session_id, {"status": "active", **self.metrics()})
        await self.emit(
            "feedback",
            result.timestamp_ms,
            {
                "source": result.source,
                "level": result.level,
                "message": result.message,
                "metrics": result.metrics,
                "transcript": result.transcript,
                "ai_latency_ms": result.latency_ms,
            },
            module=result.source,
            level="warning" if result.level == "warning" else "info",
        )
        if result.transcript:
            name = "transcript.final" if result.is_final else "transcript.partial"
            await self.emit(
                name,
                result.timestamp_ms,
                {"text": result.transcript},
                module="speech_rate",
            )
            await self._handle_transcript_analysis(result)

    async def _handle_transcript_analysis(self, result: AIResult) -> None:
        if result.transcript is None:
            return
        progress: dict[str, Any] | None = None
        if self.script_sync is not None:
            progress = self.script_sync.update(
                result.transcript,
                max(0, result.timestamp_ms - (self.running_started_ms or 0)),
                is_final=bool(result.is_final),
            )
            self.aggregator.add_script_progress(progress, result.timestamp_ms)
            if self.analysis_settings.get("karaoke_guide_enabled", True):
                await self.emit(
                    "script.progress",
                    result.timestamp_ms,
                    progress,
                    module="script_sync",
                    level="warning" if progress["pace_status"] != "on_time" else "info",
                )
        if not result.is_final or not self.analysis_settings.get("pronunciation_enabled", True):
            return
        expected = None
        if self.script_sync is not None and progress is not None:
            plan = self.script_sync.plan.timeline
            cursor = int(progress["current_token_index"])
            start = max(0, cursor - max(1, len(result.transcript.split())) + 1)
            expected = " ".join(str(item["text"]) for item in plan[start : cursor + 1])
        pronunciation = estimate_stt_pronunciation_accuracy(
            result.transcript,
            reference_text=expected,
            avg_logprob=result.metrics.get("avg_logprob"),
            no_speech_prob=result.metrics.get("no_speech_prob"),
        )
        if pronunciation.get("pronunciation_clarity_score") is None:
            return
        self.aggregator.add_pronunciation(pronunciation, result.timestamp_ms)
        level = (
            "warning"
            if pronunciation.get("pronunciation_clarity_score") is not None
            and float(pronunciation["pronunciation_clarity_score"]) < 80
            else "info"
        )
        await self.emit(
            "feedback",
            result.timestamp_ms,
            {
                "source": "pronunciation",
                "level": level,
                "message": pronunciation["message"],
                "metrics": pronunciation,
            },
            module="pronunciation",
            level=level,
        )

    def elapsed_ms(self) -> int:
        return int((time.monotonic() - self.started_monotonic) * 1000)

    def metrics(self) -> dict[str, Any]:
        return {
            "queue_depth": {
                "video": self.video_queue.qsize(),
                "audio": self.audio_queue.qsize(),
            },
            "dropped_video_frames": self.video_queue.stats.dropped,
            **self.aggregator.snapshot(),
        }
