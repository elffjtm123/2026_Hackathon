import asyncio
import hashlib
import logging
import re
import time
from collections.abc import Awaitable, Callable
from dataclasses import replace
from typing import Any, cast
from uuid import UUID

from app.ai.base import AIResult, GazeAdapter, MediaPayload, SpeechAdapter
from app.ai.model_execution import ModelExecution
from app.core.config import Settings
from app.modules.delivery.analyzer import DeliveryAnalyzer
from app.modules.gaze.service import GazeStabilizer
from app.modules.pronunciation.service import estimate_stt_pronunciation_accuracy
from app.modules.script_sync.service import ScriptSyncService, analyze_script
from app.modules.speech.analysis import (
    SpeechRateWindow,
    analyze_utterance,
    filler_counts,
    pace_message,
)
from app.modules.speech.segments import CutReason, FinalUtterance, SpeechSegmenter
from app.realtime.aggregator import FeedbackAggregator
from app.realtime.events import RealtimeEvent
from app.realtime.queues import DropOldestQueue
from app.realtime.state import SessionStateStore

Subscriber = Callable[[RealtimeEvent], Awaitable[None]]
logger = logging.getLogger(__name__)


def _delivery_counts(text: str) -> tuple[int, int]:
    """Syllables and disfluencies of a final transcript, independent of the feedback toggles."""
    fillers, repeats = filler_counts(text)
    return len(re.findall(r"[가-힣]", text)), sum(fillers.values()) + repeats


class SessionPipeline:
    def __init__(
        self,
        session_id: UUID,
        settings: Settings,
        state_store: SessionStateStore,
        gaze: GazeAdapter,
        speech: SpeechAdapter,
        analysis_settings: dict[str, bool],
        execution: ModelExecution | None = None,
    ) -> None:
        self.session_id = session_id
        self.settings = settings
        self.state_store = state_store
        self.gaze = gaze
        self.speech = speech
        self.analysis_settings = analysis_settings
        self.execution = execution
        self._execution_acquired = False
        self.video_queue: DropOldestQueue[MediaPayload] = DropOldestQueue(settings.video_queue_size)
        self.audio_queue: asyncio.Queue[MediaPayload] = asyncio.Queue(settings.audio_queue_size)
        self.speech_queue: asyncio.Queue[MediaPayload] = asyncio.Queue(2)
        self.segmenter: SpeechSegmenter | None = None
        self.speech_window = SpeechRateWindow()
        self.delivery: DeliveryAnalyzer | None = None
        self.delivery_failed = False
        self.delivery_sentence_index = 0
        self.agc_on: bool | None = None
        self.legacy_utterance_sequence = 0
        self.last_audio_activity_ms = 0
        self.latest_audio_end_ms = 0
        self.speech_waiting = False
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
        self.audio_receipts: dict[int, bytes] = {}
        script = analysis_settings.get("script")
        time_limit = analysis_settings.get("time_limit_seconds")
        self.script_sync: ScriptSyncService | None = None
        if isinstance(script, str) and script and isinstance(time_limit, int) and time_limit > 0:
            self.script_sync = ScriptSyncService(analyze_script(script, time_limit))

    def update_analysis_settings(self, settings: dict[str, Any]) -> None:
        self.analysis_settings.update(settings)
        if not self.analysis_settings.get("delivery_enabled", True):
            self.delivery = None
        script = self.analysis_settings.get("script")
        time_limit = self.analysis_settings.get("time_limit_seconds")
        if isinstance(script, str) and script and isinstance(time_limit, int) and time_limit > 0:
            self.script_sync = ScriptSyncService(analyze_script(script, time_limit))

    def set_audio_settings(self, raw: Any) -> None:
        """Remember the browser's applied auto gain control; non-bool values are ignored."""
        value = raw.get("autoGainControl") if isinstance(raw, dict) else None
        self.agc_on = value if isinstance(value, bool) else None

    def _feedback_speech_enabled(self) -> bool:
        return bool(
            self.analysis_settings.get("speech_rate_enabled", True)
            or self.analysis_settings.get("filler_words_enabled", True)
        )

    def _speech_needed(self) -> bool:
        """Speech runs for its own feedback or, via the transcript counts, for delivery."""
        return self._feedback_speech_enabled() or bool(
            self.analysis_settings.get("delivery_enabled", True)
        )

    async def start(self) -> None:
        await self.prepare()
        await self.start_running()

    async def prepare(self) -> None:
        if self.running:
            return
        if self.execution is not None:
            await self.execution.start_session(self.session_id)
            self._execution_acquired = True
        for enabled, adapter in [
            (self.analysis_settings.get("gaze_enabled", True), self.gaze),
            (self._speech_needed(), self.speech),
        ]:
            if enabled and (
                hasattr(adapter, "reason") or getattr(getattr(adapter, "gate", None), "busy", False)
            ):
                if self.execution is not None:
                    await self.execution.stop_session(self.session_id)
                    self._execution_acquired = False
                raise ValueError("MODEL_UNAVAILABLE_OR_BUSY")
        self.running = True
        self.started_monotonic = time.monotonic()
        self.tasks = [
            asyncio.create_task(self._video_worker(), name=f"video-{self.session_id}"),
            asyncio.create_task(self._audio_worker(), name=f"audio-{self.session_id}"),
            asyncio.create_task(self._speech_worker(), name=f"speech-{self.session_id}"),
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
        # Segmenter frame times are on the session clock, so windows start at the audio origin.
        self.delivery = (
            DeliveryAnalyzer(origin_ms=self.audio_origin_ms)
            if self.analysis_settings.get("delivery_enabled", True)
            else None
        )
        self.delivery_failed = False
        self.delivery_sentence_index = 0
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
            running_end_ms = self.elapsed_ms()
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
                    await self.speech_queue.join()

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

            delivery_metrics = self._delivery_metrics()
            report = {
                **self.aggregator.report(
                    self.running_started_ms
                    if self.running_started_ms is not None
                    else running_end_ms,
                    running_end_ms,
                    settings=self.analysis_settings,
                ),
                "incomplete": incomplete or self.incomplete,
                "delivery_metrics": delivery_metrics,
            }
            self.segmenter = None
            self.audio_receipts.clear()
            for queue in [self.audio_queue, self.speech_queue, self.video_queue.queue]:
                while not queue.empty():
                    queue.get_nowait()
                    queue.task_done()
            if self.execution is not None and self._execution_acquired:
                await self.execution.stop_session(self.session_id)
                self._execution_acquired = False
            self.phase = "completed"
            self.completed_report = report
            await self.state_store.set(
                self.session_id,
                {"status": "completed", **self.metrics()},
            )
            # Delivery features are never shown live; they are persisted from completed_report.
            data: dict[str, Any] = {
                "report": {k: v for k, v in report.items() if k != "delivery_metrics"}
            }
            if self.execution is not None:
                data["modules"] = {
                    name: module.model_dump()
                    for name, module in self.execution.runtime.modules.items()
                }
            await self.emit("session.completed", self.elapsed_ms(), data)
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
                if not self._speech_needed():
                    continue
                if media.format not in {"pcm16", "flush"}:
                    await self._enqueue_speech(media)
                    continue
                if self.segmenter is None:
                    self.segmenter = SpeechSegmenter(
                        silence_rms_threshold=self.settings.stt_silence_rms_threshold,
                        observe_frame=self._observe_delivery_frame,
                    )
                segments = (
                    self.segmenter.flush()
                    if media.format == "flush"
                    else self.segmenter.feed(media)
                )
                if media.format == "pcm16":
                    self.latest_audio_end_ms = media.timestamp_ms + len(media.payload) // 32
                if segments:
                    self.speech_waiting = False
                for segment in segments:
                    self.last_audio_activity_ms = segment.end_ms
                    await self._enqueue_speech(
                        MediaPayload(
                            self.session_id,
                            segment.start_ms,
                            segment.pcm,
                            start_sample=segment.start_sample,
                            sample_count=len(segment.pcm) // 2,
                            format="pcm16",
                            utterance_id=segment.utterance_id,
                            end_ms=segment.end_ms,
                            voiced_ms=segment.voiced_ms,
                            cut_reason=segment.cut_reason,
                        )
                    )
                if media.format == "pcm16":
                    end_ms = media.timestamp_ms + len(media.payload) // 32
                    if self.segmenter.speaking:
                        self.last_audio_activity_ms = end_ms
                        self.speech_waiting = False
                    elif end_ms - self.last_audio_activity_ms >= 1500 and not self.speech_waiting:
                        self.speech_waiting = True
                        if self._feedback_speech_enabled():
                            await self._handle_result(
                                AIResult(
                                    "speech_rate",
                                    end_ms,
                                    "info",
                                    "음성 대기 중입니다.",
                                    {
                                        "pace": "unknown",
                                        "syllables_per_minute": None,
                                        "filler_counts": {},
                                        "filler_words": [],
                                    },
                                )
                            )
            except asyncio.CancelledError:
                raise
            except ValueError as exc:
                self.incomplete = True
                await self.emit_error(str(exc), "음성 샘플의 순서·형식을 확인할 수 없습니다.")
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

    async def _enqueue_speech(self, media: MediaPayload) -> None:
        try:
            await asyncio.wait_for(
                self.speech_queue.put(media), self.settings.audio_queue_wait_seconds
            )
        except asyncio.TimeoutError:
            self.incomplete = True
            await self.emit_error("UTTERANCE_QUEUE_FULL", "발화 분석 대기량이 한도를 초과했습니다.")

    async def _speech_worker(self) -> None:
        while True:
            media = await self.speech_queue.get()
            observed = False
            try:
                if not self._feedback_speech_enabled():
                    # Delivery still needs the transcript for its counts, but no feedback is shown.
                    if (
                        self.delivery is not None
                        and not self.delivery_failed
                        and media.format == "pcm16"
                    ):
                        try:
                            transcript = (await self.speech.infer(media)).transcript or ""
                        except Exception:
                            logger.exception(
                                "delivery_transcription_failed",
                                extra={"session_id": self.session_id},
                            )
                            transcript = ""
                        await self._observe_delivery_utterance(
                            media, *_delivery_counts(transcript.strip())
                        )
                    continue
                result = await self.speech.infer(media)
                if not result.transcript:
                    if result.metrics.get("recognition_status") == "rejected":
                        self.incomplete = True
                    await self._handle_result(replace(result, is_final=False))
                    observed = True
                    await self._observe_delivery_utterance(media, 0, 0)
                    continue
                self.legacy_utterance_sequence += 1
                final = FinalUtterance(
                    media.utterance_id or f"legacy-u{self.legacy_utterance_sequence}",
                    media.timestamp_ms,
                    media.end_ms
                    if media.end_ms is not None
                    else media.timestamp_ms
                    + round(float(result.metrics.get("duration_sec", 0) or 0) * 1000),
                    media.voiced_ms
                    if media.voiced_ms is not None
                    else round(float(result.metrics.get("duration_sec", 0) or 0) * 1000),
                    (result.transcript or "").strip(),
                )
                metrics = analyze_utterance(
                    final,
                    rate_enabled=self.analysis_settings.get("speech_rate_enabled", True),
                    fillers_enabled=self.analysis_settings.get("filler_words_enabled", True),
                )
                self.speech_window.add(final, metrics)
                recent = self.speech_window.snapshot(
                    max(final.end_ms, self.latest_audio_end_ms, self.elapsed_ms())
                )
                live_pace = "unknown" if self.speech_waiting else recent.pace
                live_rate = None if live_pace == "unknown" else recent.syllables_per_minute
                result = replace(
                    result,
                    metrics={
                        **result.metrics,
                        **metrics.as_dict(),
                        "utterance_id": final.utterance_id,
                        "revision": final.revision,
                        "start_ms": final.start_ms,
                        "end_ms": final.end_ms,
                        "syllables_per_minute": live_rate,
                        "pace": live_pace,
                        "filler_words": [
                            {"word": word, "count": count}
                            for word, count in metrics.filler_counts.items()
                        ],
                    },
                    is_final=True,
                    transcript=final.text or None,
                    level="warning" if live_pace in {"fast", "slow"} else "info",
                    message="음성 대기 중입니다."
                    if self.speech_waiting
                    else pace_message(live_pace, live_rate),
                )
                await self._handle_result(result)
                observed = True
                await self._observe_delivery_utterance(media, *_delivery_counts(final.text))
            except asyncio.CancelledError:
                raise
            except Exception:
                self.incomplete = True
                logger.exception("speech_inference_failed", extra={"session_id": self.session_id})
                await self.emit_error("SPEECH_AI_UNAVAILABLE", "음성 분석에 실패했습니다.")
                if not observed:
                    await self._observe_delivery_utterance(media, 0, 0)
            finally:
                self.speech_queue.task_done()

    def _observe_delivery_frame(self, start_ms: int, end_ms: int, rms: float, voiced: bool) -> None:
        if self.delivery is None or self.delivery_failed:
            return
        try:
            self.delivery.observe_frame(start_ms, end_ms, rms, voiced)
        except Exception:
            self._fail_delivery()

    async def _observe_delivery_utterance(
        self, media: MediaPayload, syllables: int, disfluencies: int
    ) -> None:
        """Hand one VAD segment to the analyzer; it must never take the speech worker down."""
        analyzer = self.delivery
        if analyzer is None or self.delivery_failed or media.format != "pcm16":
            return
        try:
            await asyncio.to_thread(
                analyzer.observe_utterance,
                media.timestamp_ms,
                media.end_ms if media.end_ms is not None else media.timestamp_ms,
                media.payload,
                cast(CutReason, media.cut_reason or "endpoint"),
                self.delivery_sentence_index,
                syllables,
                disfluencies,
            )
        except asyncio.CancelledError:
            # The thread keeps running after cancellation; its state may be half updated.
            self.delivery_failed = True
            raise
        except Exception:
            self._fail_delivery()

    def _fail_delivery(self) -> None:
        self.delivery_failed = True
        logger.exception("delivery_analysis_failed", extra={"session_id": self.session_id})

    def _delivery_metrics(self) -> dict[str, Any]:
        if not self.analysis_settings.get("delivery_enabled", True):
            return {"status": "disabled"}
        analyzer = self.delivery
        if analyzer is not None and not self.delivery_failed:
            try:
                report = analyzer.report()
                return {
                    "status": report["status"],
                    "agc_on": self.agc_on,
                    "report": report,
                    "windows": analyzer.windows(),
                }
            except Exception:
                self._fail_delivery()
        return {
            "status": "failed" if analyzer is not None else "unavailable",
            "agc_on": self.agc_on,
            "report": None,
            "windows": None,
        }

    async def _handle_result(self, result: AIResult) -> None:
        if self.phase not in {"running", "draining"}:
            return
        if not self.aggregator.add(result):
            return
        if result.source == "speech_rate":
            result = replace(
                result,
                metrics={
                    **result.metrics,
                    "filler_counts_total": dict(self.aggregator.fillers),
                    "filler_status": "disabled"
                    if not self.analysis_settings.get("filler_words_enabled", True)
                    else "unavailable"
                    if not self.aggregator.transcript
                    else "observed"
                    if self.aggregator.fillers
                    else "observed_zero",
                    "warning_episode_count": self.aggregator.speech_warning_episodes,
                    "transcript_snapshot": self.aggregator.transcript,
                },
            )
        # Publish before storage can yield to a newer result. emit's lock preserves event order.
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
                {
                    "text": result.transcript,
                    "utterance_id": result.metrics.get("utterance_id"),
                    "revision": result.metrics.get("revision", 1),
                    "start_ms": result.metrics.get("start_ms", result.timestamp_ms),
                    "end_ms": result.metrics.get("end_ms"),
                    "voiced_ms": result.metrics.get("voiced_ms"),
                },
                module="speech_rate",
            )
            await self._handle_transcript_analysis(result)
        await self.state_store.set(self.session_id, {"status": "active", **self.metrics()})

    async def _handle_transcript_analysis(self, result: AIResult) -> None:
        if result.transcript is None:
            return
        progress: dict[str, Any] | None = None
        if self.script_sync is not None:
            progress = self.script_sync.update(
                result.transcript,
                max(
                    0,
                    int(result.metrics.get("end_ms", result.timestamp_ms))
                    - (self.running_started_ms or 0),
                ),
                is_final=bool(result.is_final),
            )
            self.aggregator.add_script_progress(progress, result.timestamp_ms)
            index = progress.get("current_sentence_index")
            if isinstance(index, int):
                # The analyzer rejects a decreasing sentence_index, so progress is clamped.
                self.delivery_sentence_index = max(self.delivery_sentence_index, index)
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
        if (
            self.script_sync is not None
            and progress is not None
            and progress["alignment_status"] == "matched"
        ):
            plan = self.script_sync.plan.timeline
            start = int(progress["matched_start_token"])
            end = int(progress["matched_end_token"])
            expected = " ".join(str(item["text"]) for item in plan[start : end + 1])
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
                "utterances": self.speech_queue.qsize(),
            },
            "dropped_video_frames": self.video_queue.stats.dropped,
            **self.aggregator.snapshot(),
        }
