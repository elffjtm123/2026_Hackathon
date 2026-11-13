import asyncio
import io
import wave
from types import SimpleNamespace

import numpy as np
import pytest

from app.ai.base import AIResult
from app.ai.experimental_stt import MODEL_IDS, clean_qwen_text
from app.core.config import Settings
from app.services.stt_experiments import (
    MAX_AUDIO_BYTES,
    ExperimentManager,
    character_error_rate,
    read_wav,
)


def wav(seconds=2.25, rate=16000, channels=1, sample=1000):
    output = io.BytesIO()
    with wave.open(output, "wb") as stream:
        stream.setnchannels(channels)
        stream.setsampwidth(2)
        stream.setframerate(rate)
        stream.writeframes(np.full(int(rate * seconds * channels), sample, dtype="<i2").tobytes())
    return output.getvalue()


class Speech:
    device = "cpu"

    def __init__(self):
        self.samples = []

    async def infer(self, media):
        self.samples.append(media.payload)
        return AIResult("speech_rate", 0, "info", "", {}, transcript="반복")


class Engine:
    metadata = {"engine": "test-only"}

    def __init__(self):
        self.samples = []
        self.closed = False

    def transcribe(self, audio):
        self.samples.append(audio.copy())
        return "반복"

    def close(self):
        self.closed = True


def manager(tmp_path, monkeypatch):
    settings = Settings(_env_file=None, stt_experiment_model_dir=str(tmp_path))
    result = ExperimentManager(settings, Speech())
    monkeypatch.setattr(
        result,
        "models",
        lambda: [{"id": model, "available": True, "reason": "test"} for model in MODEL_IDS],
    )
    monkeypatch.setattr("app.services.stt_experiments.has_speech", lambda *_: True)
    return result


def test_cer_normalization_missing_reference_and_insertions():
    assert character_error_rate("안녕, CPU!", "안녕 cpu") == 0
    assert character_error_rate("", "임의 문장") is None
    assert character_error_rate("...", "문장") is None
    assert character_error_rate("가", "가나다") == 2
    assert character_error_rate("가나다", "") == 1


@pytest.mark.parametrize(
    "payload",
    [b"bad", wav(rate=8000), wav(channels=2), wav(0), wav(61)],
    ids=["invalid-header", "wrong-rate", "stereo", "empty", "too-long"],
)
def test_wav_contract_rejects_invalid_audio(payload):
    with pytest.raises(ValueError):
        read_wav(payload)


def test_wav_rejects_truncated_body():
    with pytest.raises(ValueError, match="잘렸"):
        read_wav(wav()[:-10])


def test_qwen_parser_does_not_drop_actual_words():
    assert (
        clean_qwen_text("language Korean<asr_text>어, 음 반복 반복<|im_end|>") == "어, 음 반복 반복"
    )
    assert clean_qwen_text("그냥 문장") == "그냥 문장"


@pytest.mark.asyncio
async def test_same_audio_tail_and_real_repetitions_are_preserved(tmp_path, monkeypatch):
    service = manager(tmp_path, monkeypatch)
    engine = Engine()
    monkeypatch.setattr("app.services.stt_experiments.create_engine", lambda *_: engine)
    pcm = read_wav(wav())
    job = service.start(pcm, ["service_qwen", "whisper_base_int8"], "반복 반복", 2, True, False)
    await service.task
    assert job["state"] == "completed"
    for result in job["results"]:
        assert result["state"] == "completed"
        assert result["transcript"] == "반복 반복"
        assert [c["duration_seconds"] for c in result["chunks"]] == [2, 0.25]
        assert result["metrics"]["cer"] == 0
        assert "process_tree_peak_rss_mb" in result["memory"]
    assert b"".join(service.speech.samples) == pcm
    reconstructed = np.concatenate(engine.samples) * 32768
    assert reconstructed.astype("<i2").tobytes() == pcm
    assert engine.closed
    assert not service.busy


@pytest.mark.asyncio
async def test_silence_skips_every_engine_and_warmup(tmp_path, monkeypatch):
    service = manager(tmp_path, monkeypatch)
    engine = Engine()
    monkeypatch.setattr("app.services.stt_experiments.create_engine", lambda *_: engine)
    job = service.start(read_wav(wav(sample=0)), ["whisper_base_int8"], "", 2, True, True)
    await service.task
    result = job["results"][0]
    assert not engine.samples
    assert result["transcript"] == ""
    assert result["warmup_ms"] is None
    assert result["metrics"]["skipped_chunks"] == 2
    assert result["metrics"]["cer"] is None


@pytest.mark.asyncio
async def test_warmup_not_counted_in_transcript_or_chunk_metrics(tmp_path, monkeypatch):
    service = manager(tmp_path, monkeypatch)
    engine = Engine()
    monkeypatch.setattr("app.services.stt_experiments.create_engine", lambda *_: engine)
    job = service.start(read_wav(wav(2)), ["whisper_base_int8"], "", 2, True, True)
    await service.task
    assert len(engine.samples) == 2
    assert job["results"][0]["transcript"] == "반복"
    assert len(job["results"][0]["chunks"]) == 1


@pytest.mark.asyncio
async def test_unavailable_model_is_not_substituted_and_next_model_runs(tmp_path, monkeypatch):
    service = manager(tmp_path, monkeypatch)
    monkeypatch.setattr(
        service,
        "models",
        lambda: [
            {"id": model, "available": model != "qwen_q8", "reason": "weights missing"}
            for model in MODEL_IDS
        ],
    )
    job = service.start(read_wav(wav()), ["qwen_q8", "service_qwen"], "", 2, True, False)
    await service.task
    assert job["results"][0]["state"] == "failed"
    assert job["results"][0]["metrics"] is None
    assert job["results"][0]["transcript"] == ""
    assert job["results"][1]["state"] == "completed"


@pytest.mark.asyncio
async def test_busy_and_cancel_wait_for_inflight_inference(tmp_path, monkeypatch):
    service = manager(tmp_path, monkeypatch)
    entered, release = asyncio.Event(), asyncio.Event()

    async def slow(*args):
        entered.set()
        await release.wait()
        return "실제 결과"

    monkeypatch.setattr(service, "transcribe", slow)
    job = service.start(read_wav(wav(4)), ["service_qwen"], "", 2, True, False)
    await entered.wait()
    with pytest.raises(ValueError):
        service.start(read_wav(wav()), ["service_qwen"], "", 2, True, False)
    job["cancel_requested"] = True
    assert service.busy
    release.set()
    await service.task
    assert job["state"] == "cancelled"
    assert job["results"][0]["state"] == "cancelled"
    assert not service.busy


def test_api_validation_missing_reference_and_export_shape(client, monkeypatch):
    service = client.app.state.stt_experiments
    monkeypatch.setattr(
        service, "models", lambda: [{"id": "service_qwen", "available": True, "reason": "test"}]
    )
    monkeypatch.setattr(service, "speech", Speech())
    monkeypatch.setattr("app.services.stt_experiments.has_speech", lambda *_: True)
    response = client.post(
        "/api/v1/stt-experiments/jobs",
        data={"models": '["service_qwen"]'},
        files={"audio": ("test.wav", wav())},
    )
    assert response.status_code == 202
    job_id = response.json()["id"]
    # Wait through the TestClient event loop without an arbitrary sleep.
    client.portal.call(lambda: service.task)
    result = client.get(f"/api/v1/stt-experiments/jobs/{job_id}").json()
    assert result["state"] == "completed"
    assert result["results"][0]["metrics"]["cer"] is None
    assert len(result["audio_sha256"]) == 64
    assert "audio" not in result


@pytest.mark.parametrize("models", ["[]", '["unknown"]', '["qwen_q8","qwen_q8"]', "{}", "bad"])
def test_invalid_models_do_not_start_jobs(client, models):
    response = client.post(
        "/api/v1/stt-experiments/jobs",
        data={"models": models},
        files={"audio": ("test.wav", wav())},
    )
    assert response.status_code == 400
    assert not client.app.state.stt_experiments.busy


def test_oversized_upload_and_production_disabled(client):
    response = client.post(
        "/api/v1/stt-experiments/jobs",
        data={"models": '["qwen_q8"]'},
        files={"audio": ("test.wav", b"x" * (MAX_AUDIO_BYTES + 1))},
    )
    assert response.status_code == 413
    client.app.state.settings.app_env = "production"
    assert client.get("/api/v1/stt-experiments/models").status_code == 404


def test_experiments_refuse_active_sessions(client):
    client.app.state.experiment_session_count = 1
    response = client.post(
        "/api/v1/stt-experiments/jobs",
        data={"models": '["qwen_q8"]'},
        files={"audio": ("test.wav", wav())},
    )
    assert response.status_code == 409


def test_experiments_refuse_active_webrtc_connection(client):
    client.app.state.webrtc.connections["test-only"] = {object()}
    try:
        response = client.post(
            "/api/v1/stt-experiments/jobs",
            data={"models": '["qwen_q8"]'},
            files={"audio": ("test.wav", wav())},
        )
        assert response.status_code == 409
        assert client.get("/api/v1/stt-experiments/models").json()["busy"]
    finally:
        client.app.state.webrtc.connections.clear()


def test_webrtc_offer_refuses_running_experiment_and_releases_reservation(client):
    from unittest.mock import AsyncMock
    from uuid import uuid4

    from app.api.v1.sessions import webrtc_offer
    from app.core.errors import AppError
    from app.schemas.session import WebRTCOffer

    request = SimpleNamespace(app=client.app)
    client.app.state.stt_experiments.busy = True
    with pytest.raises(AppError):
        client.portal.call(
            webrtc_offer, uuid4(), WebRTCOffer(sdp="test", type="offer"), request, None, None
        )
    assert client.app.state.experiment_session_count == 0
    client.app.state.stt_experiments.busy = False

    async def fail_after_reservation(*_):
        assert client.app.state.experiment_session_count == 1
        raise ValueError("test negotiation failure")

    from unittest.mock import patch

    with patch(
        "app.api.v1.sessions._create_webrtc_answer", AsyncMock(side_effect=fail_after_reservation)
    ):
        with pytest.raises(ValueError, match="negotiation"):
            client.portal.call(
                webrtc_offer, uuid4(), WebRTCOffer(sdp="test", type="offer"), request, None, None
            )
    assert client.app.state.experiment_session_count == 0


def test_unknown_job_and_cancel(client):
    assert client.get("/api/v1/stt-experiments/jobs/not-found").status_code == 404
    assert client.post("/api/v1/stt-experiments/jobs/not-found/cancel").status_code == 404


def test_local_only_guard_and_disable_flag(client, monkeypatch):
    from starlette.testclient import TestClient
    client.app.state.settings.app_env = "development"
    external = TestClient(client.app, client=('192.0.2.1', 50000))
    assert external.get("/api/v1/stt-experiments/models").status_code == 403
    client.app.state.settings.app_env = "test"
    client.app.state.settings.stt_experiments_enabled = False
    assert client.get("/api/v1/stt-experiments/models").status_code == 404


def test_default_catalog_requires_cpu_baseline(tmp_path):
    from app.ai.experimental_stt import catalog

    result = catalog(tmp_path, SimpleNamespace(device="mps"))
    assert not result[0]["available"]
    assert all(not model["available"] for model in result)
