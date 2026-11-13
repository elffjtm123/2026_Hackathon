"""Bounded, serial, in-memory experiments against the existing service adapter."""

import asyncio
import gc
import hashlib
import importlib.metadata
import io
import json
import platform
import threading
import time
import unicodedata
import wave
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from app.ai.base import MediaPayload
from app.ai.experimental_stt import LABELS, catalog, create_engine, service_threads
from app.ai.local_stt import has_speech
from app.modules.speech.analysis import filler_counts

MAX_AUDIO_BYTES = 16000 * 2 * 60 + 4096


def read_wav(payload: bytes) -> bytes:
    try:
        with wave.open(io.BytesIO(payload), "rb") as stream:
            if (stream.getnchannels(), stream.getsampwidth(), stream.getframerate()) != (
                1,
                2,
                16000,
            ):
                raise ValueError("16kHz · mono · PCM16 WAV 파일만 사용할 수 있습니다.")
            count = stream.getnframes()
            if not 1600 <= count <= 16000 * 60:
                raise ValueError("음성 길이는 0.1초 이상, 60초 이하여야 합니다.")
            pcm = stream.readframes(count)
            if len(pcm) != count * 2:
                raise ValueError("WAV 데이터가 잘렸습니다.")
            return pcm
    except (wave.Error, EOFError) as exc:
        raise ValueError("올바른 PCM16 WAV 파일이 아닙니다.") from exc


def normalized(text: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFC", text).lower() if c.isalnum())


def character_error_rate(reference: str, hypothesis: str) -> float | None:
    reference, hypothesis = normalized(reference), normalized(hypothesis)
    if not reference:
        return None
    previous = list(range(len(hypothesis) + 1))
    for row, expected in enumerate(reference, 1):
        current = [row]
        for col, actual in enumerate(hypothesis, 1):
            current.append(
                min(current[-1] + 1, previous[col] + 1, previous[col - 1] + (expected != actual))
            )
        previous = current
    return previous[-1] / len(reference)


class MemorySampler:
    """Sample the entire backend + child process RSS, NOT model-only RAM."""

    def __init__(self) -> None:
        import psutil

        self.process = psutil.Process()
        self.psutil = psutil
        self.stop = threading.Event()
        self.before = self.measure()
        self.peak = self.before
        self.thread = threading.Thread(target=self.sample, daemon=True)

    def measure(self) -> int:
        total = 0
        for process in [self.process, *self.process.children(recursive=True)]:
            try:
                total += process.memory_info().rss
            except self.psutil.Error:
                pass
        return total

    def sample(self) -> None:
        while not self.stop.wait(0.05):
            self.peak = max(self.peak, self.measure())

    def start(self) -> None:
        self.thread.start()

    def finish(self) -> dict[str, float]:
        self.peak = max(self.peak, self.measure())
        self.stop.set()
        self.thread.join(timeout=1)
        return {
            "process_tree_peak_rss_mb": round(self.peak / 1048576, 1),
            "process_tree_rss_increase_mb": round(max(0, self.peak - self.before) / 1048576, 1),
        }


class ExperimentManager:
    def __init__(self, settings: Any, speech: Any, execution: Any = None) -> None:
        self.settings, self.speech = settings, speech
        self.execution = execution
        self.root = Path(settings.stt_experiment_model_dir)
        self.jobs: dict[str, dict[str, Any]] = {}
        self.task: asyncio.Task[None] | None = None
        self.busy = False

    def models(self) -> list[dict[str, Any]]:
        return catalog(self.root, self.speech)

    def start(
        self,
        pcm: bytes,
        model_ids: list[str],
        reference: str,
        chunk_seconds: int,
        warmup: bool,
    ) -> dict[str, Any]:
        if self.busy:
            raise ValueError("다른 비교 실험이 실행 중입니다.")
        job_id = str(uuid4())
        job: dict[str, Any] = {
            "id": job_id,
            "state": "running",
            "cancel_requested": False,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "audio_sha256": hashlib.sha256(pcm).hexdigest(),
            "audio_seconds": len(pcm) / 32000,
            "reference": reference,
            "chunk_seconds": chunk_seconds,
            # Always on: the service STT's own RMS/VAD gate cannot be bypassed for comparison.
            "use_gate": True,
            "warmup": warmup,
            "models": model_ids,
            "results": [],
            "progress": None,
            "environment": {
                "platform": platform.platform(),
                "processor": platform.processor(),
                "threads": self.settings.stt_experiment_threads,
                "device": "service-selected device; alternative candidates CPU",
                "context": getattr(self.settings, "stt_context", ""),
                "packages": {},
            },
            "notes": [
                "동일 음성 순차 실험: WebSocket·네트워크·동시 시선 분석 지연 제외.",
                "Zipformer도 청크마다 상태 초기화: 네이티브 스트리밍 최적 성능 실험 아님.",
                "전사는 청크 순서대로 합치며 실제 반복 발화를 삭제하지 않음.",
                "RAM은 기존 Qwen·시선 모델을 포함한 백엔드와 자식 프로세스 RSS 합계(50ms 표본).",
                "CER은 공백·문장부호 제외, 영문 소문자화. 정답 미입력 시 미측정, 100% 초과 가능.",
                "필러워드 수는 전사 기반 통계이며 실제 검출 정확도를 뜻하지 않음.",
                "현재 서비스는 speech.cpp Q8_0, 비교 Q8은 llama.cpp: "
                "실행 엔진과 장치가 다를 수 있음.",
                "후보는 설정된 CPU 스레드 수 사용. 기존 서비스는 현재 설정 유지, metadata에 기록.",
                "공통 게이트 전처리 시간 제외, 기존 서비스 내부의 중복 검사·후처리 시간은 포함.",
                "기존 서비스는 이미 로딩된 모델: 로딩 표시 0ms는 콜드 스타트 비용 0을 뜻하지 않음.",
            ],
        }
        for package in ("qwen-asr", "faster-whisper", "ctranslate2", "sherpa-onnx", "torch"):
            try:
                job["environment"]["packages"][package] = importlib.metadata.version(package)
            except importlib.metadata.PackageNotFoundError:
                pass
        manifest = self.root / "manifest.json"
        if manifest.is_file():
            job["environment"]["model_revisions"] = json.loads(manifest.read_text(encoding="utf-8"))
        while len(self.jobs) >= 10:
            self.jobs.pop(next(iter(self.jobs)))
        self.jobs[job_id] = job
        self.busy = True  # Reserve before creating a background task; no racing requests.
        self.task = asyncio.create_task(self.run(job, pcm))
        return job

    async def transcribe(self, engine: Any, model_id: str, pcm: bytes, index: int) -> str:
        if model_id == "service_qwen":
            result = await self.speech.infer(
                MediaPayload(
                    uuid4(),
                    index * 2000,
                    pcm,
                    format="pcm16",
                    sample_count=len(pcm) // 2,
                )
            )
            return result.transcript or ""
        import numpy as np

        audio = np.frombuffer(pcm, dtype="<i2").astype(np.float32) / 32768
        return await asyncio.to_thread(engine.transcribe, audio)

    async def run(self, job: dict[str, Any], pcm: bytes) -> None:
        owner = uuid4()
        try:
            if self.execution is not None:
                await self.execution.start_session(owner)
            for model_id in job["models"]:
                if job["cancel_requested"]:
                    break
                await self.run_model(job, pcm, model_id)
            job["state"] = "cancelled" if job["cancel_requested"] else "completed"
        except Exception as exc:
            job["state"], job["error"] = "failed", str(exc)[:500]
        finally:
            if self.execution is not None:
                await self.execution.stop_session(owner)
            job["progress"] = None
            self.busy = False

    async def run_model(self, job: dict[str, Any], pcm: bytes, model_id: str) -> None:
        import numpy as np

        engine = None
        sampler = None
        result: dict[str, Any] = {
            "model_id": model_id,
            "label": LABELS[model_id],
            "state": "loading",
            "chunks": [],
            "transcript": "",
            "load_ms": None,
            "warmup_ms": None,
            "metrics": None,
            "error": None,
        }
        job["results"].append(result)
        try:
            available = next(m for m in self.models() if m["id"] == model_id)
            if not available["available"]:
                raise RuntimeError(available["reason"])
            sampler = MemorySampler()
            sampler.start()
            started = time.perf_counter()
            if model_id != "service_qwen":
                engine = await asyncio.to_thread(
                    create_engine,
                    model_id,
                    self.root,
                    self.settings.stt_experiment_threads,
                    getattr(self.settings, "stt_context", ""),
                )
            result["load_ms"] = round((time.perf_counter() - started) * 1000, 2)
            result["metadata"] = (
                engine.metadata
                if engine
                else {
                    "engine": "existing_service_adapter",
                    "precision": "Q8_0",
                    "device": getattr(self.speech, 'device', None),
                    "load_policy": "shared realtime worker loaded for this experiment",
                }
            )
            if not engine:
                result["metadata"]["threads"] = service_threads()
            size = job["chunk_seconds"] * 32000
            chunks = [pcm[start : start + size] for start in range(0, len(pcm), size)]
            gates = []
            for chunk in chunks:
                audio = np.frombuffer(chunk, dtype="<i2").astype(np.float32) / 32768
                rms = float(np.sqrt(np.mean(audio * audio)))
                voiced = rms >= self.settings.stt_silence_rms_threshold and has_speech(
                    audio, 16000
                )
                gates.append((voiced, rms))
            if job["warmup"] and not job["cancel_requested"]:
                first = next((i for i, (voiced, _) in enumerate(gates) if voiced), None)
                if first is not None:
                    result["state"] = "warming"
                    started = time.perf_counter()
                    await self.transcribe(engine, model_id, chunks[first], first)
                    result["warmup_ms"] = round((time.perf_counter() - started) * 1000, 2)
            result["state"] = "running"
            elapsed_ms = []
            for index, (chunk, (voiced, rms)) in enumerate(zip(chunks, gates, strict=True)):
                if job["cancel_requested"]:
                    result["state"] = "cancelled"
                    return
                job["progress"] = {"model_id": model_id, "chunk": index + 1, "total": len(chunks)}
                started = time.perf_counter()
                text = await self.transcribe(engine, model_id, chunk, index) if voiced else ""
                latency = (time.perf_counter() - started) * 1000
                elapsed_ms.append(latency)
                result["chunks"].append(
                    {
                        "index": index,
                        "start_seconds": index * job["chunk_seconds"],
                        "duration_seconds": len(chunk) / 32000,
                        "text": text,
                        "latency_ms": round(latency, 2),
                        "rms": rms,
                        "skipped": not voiced,
                    }
                )
                result["transcript"] = " ".join(c["text"] for c in result["chunks"] if c["text"])
            result["metrics"] = {
                "cer": await asyncio.to_thread(
                    character_error_rate, job["reference"], result["transcript"]
                ),
                "processing_ms": round(sum(elapsed_ms), 2),
                "rtf": round(sum(elapsed_ms) / (job["audio_seconds"] * 1000), 4),
                "p95_chunk_ms": round(float(np.percentile(elapsed_ms, 95)), 2),
                "skipped_chunks": sum(not voiced for voiced, _ in gates),
                "filler_counts": filler_counts(result["transcript"])[0],
                "gate_timing": "RMS/VAD preprocessing excluded; service internal gate included",
            }
            result["state"] = "completed"
        except Exception as exc:
            result["state"], result["error"] = "failed", str(exc)[:500]
        finally:
            if sampler:
                result["memory"] = sampler.finish()
            if engine:
                await asyncio.to_thread(engine.close)
                del engine
                await asyncio.to_thread(gc.collect)

    async def close(self) -> None:
        for job in self.jobs.values():
            job["cancel_requested"] = True
        # Native inference must finish before the model/child process is released.
        if self.task:
            await self.task
