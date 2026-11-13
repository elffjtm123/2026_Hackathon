"""One leased CPU candidate per local live session, no fallback or global replacement."""

import asyncio
import gc
import time
from pathlib import Path
from typing import Any
from uuid import UUID

from app.ai.experimental_stt import LABELS, MODEL_IDS, catalog, service_threads
from app.ai.live_stt import LiveCandidateSpeechAdapter
from app.realtime.events import ModuleStatus
from app.realtime.experiment_recorder import ExperimentRecorder


class LiveSpeechManager:
    def __init__(self, settings: Any, baseline: Any) -> None:
        self.settings, self.baseline = settings, baseline
        self.owner: UUID | None = None
        self.adapter: Any = None
        self.loading: asyncio.Task[Any] | None = None
        self.borrowed = False

    @property
    def busy(self) -> bool:
        return self.owner is not None

    async def acquire(self, owner: UUID, model_id: str) -> tuple[Any, ModuleStatus, dict]:
        if model_id not in MODEL_IDS:
            raise ValueError("INVALID_STT_MODEL")
        if self.busy:
            raise ValueError("다른 모델 연습이 실행 중입니다. 먼저 종료해 주세요.")
        self.owner = owner  # Reserve synchronously, before any native load awaits.
        self.borrowed = False
        started = time.perf_counter()
        root = Path(self.settings.stt_experiment_model_dir)
        available = next(model for model in catalog(root, self.baseline) if model["id"] == model_id)
        if not available["available"]:
            raise ValueError(available["reason"])
        if model_id == "service_qwen":
            if getattr(getattr(self.baseline, "gate", None), "busy", False):
                raise ValueError("기존 STT가 이전 음성을 처리 중입니다. 잠시 후 다시 시작하세요.")
            adapter = self.baseline
            self.borrowed = True
            self.adapter = adapter
            metadata = {"engine": "existing_service_adapter", "precision": "service_configuration"}
        else:
            self.loading = asyncio.create_task(
                asyncio.to_thread(LiveCandidateSpeechAdapter, model_id, root, self.settings)
            )
            adapter = await asyncio.shield(self.loading)
            self.adapter = adapter
            metadata = dict(adapter.engine.metadata)
        threads = (
            service_threads()
            if model_id == "service_qwen"
            else self.settings.stt_experiment_threads
        )
        info = {
            "model_id": model_id,
            "label": LABELS[model_id],
            "device": getattr(adapter, "device", None),
            "load_ms": round((time.perf_counter() - started) * 1000, 2),
            "already_loaded": model_id == "service_qwen",
            "threads": threads,
            "metadata": metadata,
            "context": getattr(self.settings, "stt_context", ""),
            "silence_rms_threshold": self.settings.stt_silence_rms_threshold,
            "segmentation": "VAD final utterances, maximum 8 seconds",
            "transport": "websocket_v2",
            "notes": [
                "얼굴·눈 시선과 음성 후처리는 모든 테마에서 동일한 서비스 구현을 사용.",
                "새 시선 보정 수행. 사용자 행동 차이도 결과에 영향; 모델만의 효과가 아님.",
                "후보별 실행 엔진·스레드도 다름. 양자화만의 인과 효과 비교가 아님.",
                "Zipformer는 현재 발화마다 스트림 초기화; 연속 스트리밍 실험 아님.",
                "현재 서비스 Q8·시선 프로세스도 실행되므로 후보 단독 메모리 비교가 아님.",
                "발음 명료도는 대본/STT 일치도 기반 추정이며 음향학적 발음 정확도가 아님.",
            ],
        }
        status = ModuleStatus(
            provider=metadata["engine"],
            model=LABELS[model_id],
            device=getattr(adapter, "device", None),
            status="ready",
        )
        return adapter, status, info

    async def release(self, owner: UUID) -> None:
        if self.owner != owner:
            return
        try:
            if self.loading is not None:
                try:
                    self.adapter = await asyncio.shield(self.loading)
                except Exception:
                    pass
            if self.adapter is not None:
                future = getattr(getattr(self.adapter, "gate", None), "future", None)
                if future is not None:
                    try:
                        await asyncio.shield(asyncio.wrap_future(future))
                    except Exception:
                        pass
                if not self.borrowed:
                    await asyncio.to_thread(self.adapter.close)
                self.adapter = None
                await asyncio.to_thread(gc.collect)
        finally:
            self.loading = None
            self.owner = None
            self.borrowed = False

    async def close(self) -> None:
        if self.owner is not None:
            await self.release(self.owner)


class SessionSpeechLease:
    """One practice WebSocket's STT choice, lent from LiveSpeechManager.

    Contract: ``attach`` runs inside every prepare attempt and first returns any lease an
    earlier failed attempt held, restoring the service adapter; ``refresh`` runs after a
    successful ``pipeline.prepare``; ``release`` runs once the pipeline has stopped, on
    every exit path. ``release`` is idempotent, so a session that never borrowed is fine.
    ``modules`` is the per-session module status the client sees.
    """

    def __init__(
        self,
        manager: LiveSpeechManager,
        session_id: UUID,
        service_speech: Any,
        module_status: dict[str, ModuleStatus],
        *,
        enabled: bool,
        authenticated: bool,
    ) -> None:
        self.manager, self.session_id = manager, session_id
        self.service_speech = service_speech
        self.service_modules = module_status  # live service status; read, never mutated
        self.modules = dict(module_status)
        self.enabled, self.authenticated = enabled, authenticated

    async def attach(self, pipeline: Any, model_id: str | None, mode: str) -> None:
        """Raises ValueError with the client-facing error code when the choice is refused."""
        await self.release()
        pipeline.speech, pipeline.experiment = self.service_speech, None
        self.modules["speech"] = self.service_modules["speech"]
        if model_id is not None and self.authenticated:
            raise ValueError("STT_SELECTION_LOCAL_DEMO_ONLY")
        if model_id is None or model_id == "service_qwen":
            return
        if not self.enabled:
            raise ValueError("STT_SELECTION_DISABLED")
        try:
            adapter, status, info = await self.manager.acquire(self.session_id, model_id)
        except Exception as exc:
            # acquire reserves before loading; return the reservation so a retry can run.
            await self.release()
            reason = str(exc)[:300]
            self.modules["speech"] = self.modules["speech"].model_copy(
                update={"status": "unavailable", "model": LABELS[model_id], "reason": reason}
            )
            raise ValueError("STT_MODEL_LOAD_FAILED") from exc
        pipeline.speech = adapter
        pipeline.experiment = ExperimentRecorder(
            {**info, "mode": mode, "gaze": self.modules["gaze"].model_dump()}
        )
        self.modules["speech"] = status

    def refresh(self, pipeline: Any) -> None:
        for name, module in self.service_modules.items():
            if name != "speech" or pipeline.experiment is None:
                self.modules[name] = module
        if pipeline.experiment is not None:
            pipeline.experiment.annotate(gaze=self.modules["gaze"].model_dump())

    async def release(self) -> None:
        await self.manager.release(self.session_id)
