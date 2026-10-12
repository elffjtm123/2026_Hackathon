import asyncio
from typing import Any
from uuid import UUID

from anyio import CancelScope

from app.ai.base import GazeAdapter, SpeechAdapter
from app.ai.script_summary import LocalScriptSummarizer
from app.core.config import Settings
from app.realtime.pipeline import SessionPipeline
from app.realtime.state import SessionStateStore


class PipelineRegistry:
    def __init__(
        self,
        settings: Settings,
        state_store: SessionStateStore,
        gaze: GazeAdapter,
        speech: SpeechAdapter,
        summarizer: LocalScriptSummarizer,
    ) -> None:
        self.settings = settings
        self.state_store = state_store
        self.gaze = gaze
        self.speech = speech
        self.summarizer = summarizer
        self.pipelines: dict[UUID, SessionPipeline] = {}
        self._lock = asyncio.Lock()

    async def get_or_create(
        self, session_id: UUID, analysis_settings: dict[str, bool], protocol: int = 1
    ) -> SessionPipeline:
        async with self._lock:
            if self.summarizer.busy:
                raise ValueError("SUMMARY_BUSY")
            pipeline = self.pipelines.get(session_id)
            if pipeline is not None and protocol == 2:
                raise ValueError("SESSION_ALREADY_CONNECTED")
            if pipeline is None:
                pipeline = SessionPipeline(
                    session_id,
                    self.settings,
                    self.state_store,
                    self.gaze,
                    self.speech,
                    analysis_settings,
                )
                pipeline.protocol = protocol
                self.pipelines[session_id] = pipeline
                try:
                    if protocol == 2:
                        await pipeline.prepare()
                    else:
                        await pipeline.start()
                except BaseException:
                    with CancelScope(shield=True):
                        try:
                            await pipeline.stop()
                        finally:
                            self.pipelines.pop(session_id, None)
                    raise
            return pipeline

    def get(self, session_id: UUID) -> SessionPipeline | None:
        return self.pipelines.get(session_id)

    async def stop(self, session_id: UUID) -> dict[str, Any] | None:
        async with self._lock:
            pipeline = self.pipelines.get(session_id)
            report = await pipeline.stop() if pipeline else None
            self.pipelines.pop(session_id, None)
            return report

    async def close(self) -> None:
        pipelines = list(self.pipelines.values())
        self.pipelines.clear()
        await asyncio.gather(*(pipeline.stop() for pipeline in pipelines), return_exceptions=True)
