import asyncio
import logging
import time
from collections.abc import Awaitable, Callable
from typing import Any
from uuid import UUID

from app.ai.base import AIResult, GazeAdapter, MediaPayload, SpeechAdapter
from app.core.config import Settings
from app.modules.pronunciation.service import estimate_pronunciation_clarity
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
        self.subscribers: dict[str, Subscriber] = {}
        self.tasks: list[asyncio.Task[None]] = []
        self.running = False
        self.accepting = False
        self.sequence = 0
        self.started_monotonic = time.monotonic()
        self._sequence_lock = asyncio.Lock()
        script = analysis_settings.get("script")
        time_limit = analysis_settings.get("time_limit_seconds")
        self.script_sync: ScriptSyncService | None = None
        if isinstance(script, str) and script and isinstance(time_limit, int) and time_limit > 0:
            self.script_sync = ScriptSyncService(analyze_script(script, time_limit))

    async def start(self) -> None:
        if self.running:
            return
        self.running = self.accepting = True
        self.started_monotonic = time.monotonic()
        self.tasks = [
            asyncio.create_task(self._video_worker(), name=f"video-{self.session_id}"),
            asyncio.create_task(self._audio_worker(), name=f"audio-{self.session_id}"),
        ]
        await self.state_store.set(self.session_id, {"status": "active", **self.metrics()})
        await self.emit("session.started", 0, {})

    def subscribe(self, subscriber_id: str, callback: Subscriber) -> None:
        self.subscribers[subscriber_id] = callback

    def unsubscribe(self, subscriber_id: str) -> None:
        self.subscribers.pop(subscriber_id, None)

    async def push_video(self, timestamp_ms: int, payload: bytes) -> None:
        if not self.accepting:
            return
        self.video_queue.put_latest(MediaPayload(self.session_id, timestamp_ms, payload))

    async def push_audio(self, timestamp_ms: int, payload: bytes) -> bool:
        if not self.accepting:
            return False
        media = MediaPayload(self.session_id, timestamp_ms, payload)
        try:
            await asyncio.wait_for(
                self.audio_queue.put(media), timeout=self.settings.audio_queue_wait_seconds
            )
            return True
        except TimeoutError:
            await self.emit_error("AUDIO_QUEUE_FULL", "오디오 처리량이 한도를 초과했습니다.")
            return False

    async def stop(self) -> dict[str, Any]:
        if not self.running:
            return self.aggregator.report()
        self.accepting = False
        try:
            await asyncio.wait_for(
                asyncio.gather(self.video_queue.queue.join(), self.audio_queue.join()),
                timeout=self.settings.pipeline_grace_seconds,
            )
        except TimeoutError:
            logger.warning("pipeline_grace_timeout", extra={"session_id": self.session_id})
        for task in self.tasks:
            task.cancel()
        await asyncio.gather(*self.tasks, return_exceptions=True)
        self.tasks.clear()
        self.running = False
        report = self.aggregator.report()
        await self.state_store.set(self.session_id, {"status": "completed", **self.metrics()})
        await self.emit("session.completed", self.elapsed_ms(), {"report": report["summary"]})
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
                    result = await self.gaze.infer(media)
                    await self._handle_result(result)
            except asyncio.CancelledError:
                raise
            except Exception:
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
                if self.analysis_settings.get("speech_rate_enabled", True):
                    result = await self.speech.infer(media)
                    await self._handle_result(result)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception(
                    "speech_inference_failed",
                    extra={"session_id": self.session_id, "error_code": "SPEECH_AI_FAILED"},
                )
                await self.emit_error("SPEECH_AI_UNAVAILABLE", "음성 분석이 일시적으로 지연됩니다.")
            finally:
                self.audio_queue.task_done()

    async def _handle_result(self, result: AIResult) -> None:
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
                "ai_latency_ms": result.latency_ms,
            },
            module=result.source,
            level="warning" if result.level == "warning" else "info",
        )
        if result.transcript:
            await self._handle_transcript_analysis(result)
            name = "transcript.final" if result.is_final else "transcript.partial"
            await self.emit(
                name,
                result.timestamp_ms,
                {"text": result.transcript},
                module="speech_rate",
            )

    async def _handle_transcript_analysis(self, result: AIResult) -> None:
        if self.script_sync is None or result.transcript is None:
            return
        progress = self.script_sync.update(
            result.transcript, result.timestamp_ms, is_final=bool(result.is_final)
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
        plan = self.script_sync.plan.timeline
        cursor = int(progress["current_token_index"])
        start = max(0, cursor - max(1, len(result.transcript.split())) + 1)
        expected = " ".join(str(item["text"]) for item in plan[start : cursor + 1])
        pronunciation = estimate_pronunciation_clarity(expected, result.transcript)
        self.aggregator.add_pronunciation(pronunciation, result.timestamp_ms)
        await self.emit(
            "feedback",
            result.timestamp_ms,
            pronunciation,
            module="pronunciation",
            level=(
                "warning"
                if pronunciation.get("pronunciation_clarity_score") is not None
                and float(pronunciation["pronunciation_clarity_score"]) < 80
                else "info"
            ),
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
