"""Model doubles here test routing/lifecycle, not accuracy of actual models."""

import asyncio
import struct
import threading
import time
from dataclasses import replace
from types import SimpleNamespace
from uuid import uuid4

import numpy as np
import pytest
from pydantic import ValidationError

from app.ai.base import MediaPayload
from app.ai.experimental_stt import LABELS, MODEL_IDS
from app.ai.live_stt import LiveCandidateSpeechAdapter
from app.core.config import Settings
from app.realtime.events import SessionStartData
from app.services.live_stt import LiveSpeechManager

TEXT = "음 오늘은 발표 연습을 시작하겠습니다"


class Engine:
    metadata = {"engine": "test-only", "precision": "fixture"}

    def __init__(self):
        self.samples = []
        self.closed = False

    def transcribe(self, audio):
        self.samples.append(audio.copy())
        return TEXT

    def close(self):
        self.closed = True


def allow_models(monkeypatch):
    monkeypatch.setattr(
        "app.services.live_stt.catalog",
        lambda *_: [{"id": model, "available": True} for model in MODEL_IDS],
    )


def candidate(monkeypatch, tmp_path, model_id):
    engine = Engine()
    monkeypatch.setattr("app.ai.live_stt.create_engine", lambda *_: engine)
    monkeypatch.setattr("app.ai.local_stt.has_speech", lambda *_: True)
    adapter = LiveCandidateSpeechAdapter(model_id, tmp_path, Settings(_env_file=None))
    return adapter, engine


@pytest.mark.asyncio
@pytest.mark.parametrize("model_id", MODEL_IDS[1:])
async def test_candidate_keeps_shared_postprocessing_and_silence_gate(
    monkeypatch, tmp_path, model_id
):
    adapter, engine = candidate(monkeypatch, tmp_path, model_id)
    try:
        silence = await adapter.infer(MediaPayload(uuid4(), 0, b"\0\0" * 16000, format="pcm16"))
        assert silence.transcript is None
        assert not engine.samples
        pcm = np.full(16000, 1000, dtype="<i2").tobytes()
        result = await adapter.infer(MediaPayload(uuid4(), 10, pcm, format="pcm16"))
        assert result.transcript == TEXT
        assert result.source == "speech_rate"
        # Rate/fillers are computed once by the common final-utterance pipeline.
        assert result.metrics["syllables_per_minute"] is None
        assert result.metrics["filler_words"] == []
        assert result.metrics["recognition_status"] == "recognized"
        assert result.latency_ms is not None
        assert len(engine.samples) == 1
    finally:
        adapter.close()
    assert engine.closed


@pytest.mark.asyncio
async def test_live_lease_uses_selected_adapter_without_mutating_baseline(monkeypatch, tmp_path):
    allow_models(monkeypatch)
    adapter, engine = candidate(monkeypatch, tmp_path, "whisper_base_int8")
    monkeypatch.setattr("app.services.live_stt.LiveCandidateSpeechAdapter", lambda *_: adapter)
    baseline = SimpleNamespace(device="cpu")
    manager = LiveSpeechManager(Settings(_env_file=None), baseline)
    owner = uuid4()
    selected, status, info = await manager.acquire(owner, "whisper_base_int8")
    assert selected is adapter and manager.baseline is baseline
    assert status.model == LABELS["whisper_base_int8"]
    assert info["model_id"] == "whisper_base_int8"
    with pytest.raises(ValueError):
        await manager.acquire(uuid4(), "service_qwen")
    await manager.release(uuid4())
    assert manager.busy and not engine.closed
    await manager.release(owner)
    assert not manager.busy and engine.closed
    selected, _, info = await manager.acquire(owner, "service_qwen")
    assert selected is baseline and info["already_loaded"]
    await manager.release(owner)
    assert manager.baseline is baseline


@pytest.mark.asyncio
async def test_unavailable_model_does_not_fall_back(monkeypatch):
    monkeypatch.setattr(
        "app.services.live_stt.catalog",
        lambda *_: [{"id": "qwen_q8", "available": False, "reason": "weights missing"}],
    )
    manager = LiveSpeechManager(Settings(_env_file=None), object())
    owner = uuid4()
    with pytest.raises(ValueError, match="weights missing"):
        await manager.acquire(owner, "qwen_q8")
    assert manager.adapter is None
    await manager.release(owner)
    assert not manager.busy


@pytest.mark.asyncio
async def test_cancelled_load_is_not_released_until_native_load_finishes(monkeypatch):
    allow_models(monkeypatch)
    entered, finish = threading.Event(), threading.Event()
    closed = []
    adapter = SimpleNamespace(engine=Engine(), device="cpu", close=lambda: closed.append(True))

    def load(*_):
        entered.set()
        assert finish.wait(3)
        return adapter

    monkeypatch.setattr("app.services.live_stt.LiveCandidateSpeechAdapter", load)
    manager = LiveSpeechManager(Settings(_env_file=None), object())
    owner = uuid4()
    task = asyncio.create_task(manager.acquire(owner, "qwen_q8"))
    assert await asyncio.to_thread(entered.wait, 2)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    cleanup = asyncio.create_task(manager.release(owner))
    await asyncio.sleep(0.02)
    assert manager.busy and not closed
    finish.set()
    await cleanup
    assert not manager.busy and closed == [True]


def control(event, sequence, session_id=None, timestamp=0, data=None):
    return {
        "version": 2,
        "event": event,
        "sequence": sequence,
        "session_id": session_id,
        "timestamp_ms": timestamp,
        "module": "system",
        "level": "info",
        "data": data or {},
    }


def until(socket, event):
    for _ in range(40):
        result = socket.receive_json()
        assert result["event"] != "error", result
        if result["event"] == event:
            return result
    raise AssertionError(f"missing {event}")


@pytest.mark.parametrize("model_id", MODEL_IDS[1:])
def test_v2_theme_keeps_gaze_calibration_audio_tail_and_report(
    client, monkeypatch, tmp_path, model_id
):
    allow_models(monkeypatch)
    from app.modules.speech.segments import SpeechSegmenter

    monkeypatch.setattr(
        "app.realtime.pipeline.SpeechSegmenter",
        lambda *args, **kwargs: SpeechSegmenter(*args, **kwargs, is_speech=lambda *_: True),
    )
    adapter, engine = candidate(monkeypatch, tmp_path, model_id)
    monkeypatch.setattr("app.services.live_stt.LiveCandidateSpeechAdapter", lambda *_: adapter)
    baseline = client.app.state.speech
    original_gaze_infer = client.app.state.gaze.infer

    async def stable_gaze(media):
        # The existing fake intentionally looks away every 7 seconds. This
        # routing test needs constant frontal observations even on a busy CPU.
        result = await original_gaze_infer(replace(media, timestamp_ms=0))
        return replace(result, timestamp_ms=media.timestamp_ms)

    monkeypatch.setattr(client.app.state.gaze, "infer", stable_gaze)
    with client.websocket_connect("/api/v1/ws/practice-demo?protocol=2") as socket:
        socket.send_json(
            control(
                "session.start",
                1,
                data={
                    "mode": "presentation",
                    "script": TEXT,
                    "timeLimitSeconds": 180,
                    "stt_model_id": model_id,
                },
            )
        )
        ready = until(socket, "session.ready")
        session_id = ready["session_id"]
        assert ready["data"]["modules"]["speech"]["model"] == LABELS[model_id]
        assert ready["data"]["modules"]["gaze"]["status"] == "ready"
        assert client.app.state.live_speech.busy
        socket.send_json(control("calibration.start", 2, session_id))
        calibration = until(socket, "session.calibrating")
        # Anchor to the server's calibration event, not a client zero that can
        # precede begin_calibration by a few ms and be correctly discarded.
        clock, offset = time.monotonic(), calibration["timestamp_ms"]
        for sequence in range(1, 9):
            timestamp = offset + round((time.monotonic() - clock) * 1000)
            socket.send_bytes(struct.pack(">BBIQQI", 2, 1, sequence, timestamp, 0, 0) + b"jpeg")
            until(socket, "feedback")
            time.sleep(0.12)
        running = until(socket, "session.running")
        origin = running["data"]["audio_origin_ms"]
        timestamp = offset + round((time.monotonic() - clock) * 1000)
        socket.send_bytes(struct.pack(">BBIQQI", 2, 1, 9, timestamp, 0, 0) + b"jpeg")
        observation = until(socket, "feedback")
        assert observation["data"]["metrics"]["calibrated"] is True
        pcm = np.full(3200, 1000, dtype="<i2").tobytes()
        for sequence in range(1, 6):
            start = (sequence - 1) * 3200
            socket.send_bytes(
                struct.pack(">BBIQQI", 2, 2, sequence, origin + start // 16, start, 3200) + pcm
            )
            until(socket, "media.ack")
        socket.send_json(control("session.end", 3, session_id, timestamp))
        report = until(socket, "session.completed")["data"]["report"]
        assert not report["incomplete"]
        assert report["transcript"] == TEXT
        assert report["filler_word_counts"]["음"] == 1
        comparison = report["comparison"]
        assert comparison["model_id"] == model_id
        assert comparison["performance"]["gaze"]["observations"] == 1
        assert comparison["performance"]["speech_rate"]["observations"] == 1
        assert comparison["errors"] == {}
        assert len(engine.samples) == 1 and len(engine.samples[0]) == 16000
    assert not client.app.state.live_speech.busy
    assert engine.closed
    assert client.app.state.speech is baseline


def test_invalid_model_is_not_accepted_by_start_schema():
    with pytest.raises(ValidationError):
        SessionStartData.model_validate({"stt_model_id": "fake-model"})


def test_disabled_theme_returns_error_without_lease(client):
    client.app.state.settings.stt_experiments_enabled = False
    with client.websocket_connect("/api/v1/ws/practice-demo?protocol=2") as socket:
        socket.send_json(control("session.start", 1, data={"stt_model_id": "qwen_q8"}))
        result = socket.receive_json()
        assert result["event"] == "error"
        assert result["data"]["code"] == "STT_SELECTION_DISABLED"
    assert not client.app.state.live_speech.busy


def test_failed_native_load_returns_reason_and_releases_lease(client, monkeypatch):
    allow_models(monkeypatch)

    def fail_load(*_):
        raise RuntimeError("candidate test weights failed to load")

    monkeypatch.setattr("app.services.live_stt.LiveCandidateSpeechAdapter", fail_load)
    baseline = client.app.state.speech
    with client.websocket_connect("/api/v1/ws/practice-demo?protocol=2") as socket:
        socket.send_json(control("session.start", 1, data={"stt_model_id": "qwen_q8"}))
        error = socket.receive_json()
        assert error["data"]["code"] == "STT_MODEL_LOAD_FAILED"
        assert "weights failed" in error["data"]["message"]
        assert error["data"]["modules"]["speech"]["status"] == "unavailable"
        assert error["data"]["modules"]["speech"]["model"] == LABELS["qwen_q8"]
    assert not client.app.state.live_speech.busy
    assert client.app.state.speech is baseline
    assert client.app.state.experiment_session_count == 0


def test_theme_lease_blocks_batch_experiment_and_other_demo_session(client):
    from starlette.websockets import WebSocketDisconnect

    client.app.state.live_speech.owner = uuid4()
    assert client.get("/api/v1/stt-experiments/models").json()["busy"]
    with pytest.raises(WebSocketDisconnect) as error:
        with client.websocket_connect("/api/v1/ws/practice-demo?protocol=2"):
            pass
    assert error.value.code == 1013
    assert client.app.state.experiment_session_count == 0
