import asyncio
import struct
from pathlib import Path

import numpy as np
import pytest

from app.services.pretrained_pulse import PretrainedPulse, prepare_pulse_tensor, read_pulse_packet


def packet(count=91, duration=3000):
    times = np.linspace(0, duration, count, dtype="<f8")
    rgb = np.random.default_rng(42).integers(40, 200, (count, 72, 72, 3), dtype=np.uint8)
    return b"EP01" + struct.pack("<HH", count, 0) + times.tobytes() + rgb.tobytes()


def test_packet_and_resampling():
    times, frames = read_pulse_packet(packet(61))
    tensor = prepare_pulse_tensor(times, frames)
    assert tensor.shape == (91, 3, 72, 72)
    assert tensor.dtype == np.float32
    assert abs(float(tensor.mean())) < 1e-5
    assert abs(float(tensor.std()) - 1) < 1e-5


@pytest.mark.parametrize(
    "payload",
    [b"", b"wrong", packet(31), packet(duration=5000), packet()[:-1]],
    ids=["empty", "magic", "few-frames", "slow", "truncated"],
)
def test_bad_packet_rejected(payload):
    with pytest.raises(ValueError):
        read_pulse_packet(payload)


def test_nonfinite_clock_rejected():
    payload = bytearray(packet())
    struct.pack_into("<d", payload, 8, float("nan"))
    with pytest.raises(ValueError):
        read_pulse_packet(payload)


def test_api_origin_and_invalid_input(client):
    assert (
        client.post(
            "/api/v1/pulse/infer", content=packet(), headers={"origin": "https://evil.example"}
        ).status_code
        == 403
    )
    headers = {"origin": "http://testserver", "content-type": "application/octet-stream"}
    assert client.post("/api/v1/pulse/infer", content=b"bad", headers=headers).status_code == 422
    assert (
        client.post(
            "/api/v1/pulse/infer", content=b"x" * (2 * 1024 * 1024 + 1), headers=headers
        ).status_code
        == 413
    )
    assert not client.app.state.pretrained_pulse.request_active


@pytest.mark.parametrize(
    ("owner", "code"),
    [
        ("summary", "SUMMARY_BUSY"),
        ("interview_plan", "INTERVIEW_BUSY"),
        ("interview_evaluation", "INTERVIEW_BUSY"),
    ],
)
def test_infer_is_rejected_while_an_offline_job_owns_the_models(client, owner, code):
    client.app.state.model_execution.owner = owner
    headers = {"origin": "http://testserver", "content-type": "application/octet-stream"}
    response = client.post("/api/v1/pulse/infer", content=packet(), headers=headers)
    assert (response.status_code, response.json()["error"]["code"]) == (409, code)


def test_infer_is_rejected_while_a_session_borrows_the_generation_model(client, monkeypatch):
    monkeypatch.setattr(type(client.app.state.model_execution), "generation_active", True)
    headers = {"origin": "http://testserver", "content-type": "application/octet-stream"}
    response = client.post("/api/v1/pulse/infer", content=packet(), headers=headers)
    assert (response.status_code, response.json()["error"]["code"]) == (409, "INTERVIEW_BUSY")


def test_missing_model_is_explicit(client, tmp_path):
    client.app.state.pretrained_pulse.directory = tmp_path
    headers = {"origin": "http://testserver", "content-type": "application/octet-stream"}
    response = client.post("/api/v1/pulse/infer", content=packet(), headers=headers)
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "PULSE_MODEL_MISSING"


async def test_actual_pretrained_output():
    directory = Path(".models/pulse")
    if not (directory / "EfficientPhys-PURE-91.onnx").exists():
        pytest.skip("Opt-in local model assets absent")
    runner = PretrainedPulse(str(directory))
    result = await runner.infer(packet())
    assert result["model"] == "EfficientPhys"
    assert len(result["values"]) == 90
    assert np.isfinite(result["values"]).all()
    assert result["inference_ms"] > 0
    await runner.close()
    assert runner.session is None


@pytest.mark.parametrize('model_id', ['ubfc_efficientphys', 'ubfc_tscan', 'ubfc_physformer','ma_ubfc_tscan'])
async def test_ubfc_real_models_and_model_specific_preprocessing(model_id):
    from app.services.pretrained_pulse import pulse_contract
    c = pulse_contract(model_id)
    runner = PretrainedPulse('.models/pulse')
    if not runner.available(model_id):
        pytest.skip('Opt-in UBFC weights absent')
    count = 161 if c['size'] == 128 else 91
    times = np.linspace(0, c['duration_ms'], count, dtype='<f8')
    frames = np.random.default_rng(42).integers(40,200,(count,c['size'],c['size'],3),dtype=np.uint8)
    data = (b'EP02' if c['size'] == 128 else b'EP01') + struct.pack('<HH',count,0) + times.tobytes() + frames.tobytes()
    tensor = prepare_pulse_tensor(times,frames,model_id)
    expected = (1,3,160,128,128) if model_id=='ubfc_physformer' else (90,6,72,72) if model_id in ('ubfc_tscan','ma_ubfc_tscan') else (91,3,72,72)
    assert tensor.shape == expected
    assert np.isfinite(tensor).all()
    result = await runner.infer(data,model_id)
    assert result['model_id'] == model_id
    assert result['training_dataset'] == ('Motion-augmented UBFC-rPPG' if model_id=='ma_ubfc_tscan' else 'UBFC-rPPG')
    assert len(result['values']) == c['outputs']
    assert result['inference_ms'] > 0
    await runner.close()


def test_unknown_model_and_wrong_packet_contract_are_explicit(client):
    response=client.get('/api/v1/pulse/model?model_id=not-a-model')
    assert response.status_code == 422
    with pytest.raises(ValueError):
        read_pulse_packet(packet(),'ubfc_physformer')
    models=client.get('/api/v1/pulse/model?model_id=ubfc_tscan').json()['models']
    assert {v['id'] for v in models} == {'pure_efficientphys','ubfc_efficientphys','ubfc_tscan','ubfc_physformer','ma_ubfc_tscan'}


async def test_cancelled_inference_holds_slot_until_real_work_finishes(monkeypatch, tmp_path):
    import threading

    runner = PretrainedPulse(str(tmp_path))
    monkeypatch.setattr(runner, "available", lambda: True)
    started = threading.Event()
    release = threading.Event()

    def slow(*args):
        started.set()
        release.wait(3)
        return {}

    monkeypatch.setattr(runner, "_run", slow)
    task = asyncio.create_task(runner.infer(packet()))
    await asyncio.to_thread(started.wait, 1)
    task.cancel()
    await asyncio.sleep(0.01)
    assert runner.busy
    release.set()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert not runner.busy


BUNDLED = Path(__file__).resolve().parents[1] / "app" / "assets" / "pulse"


def test_default_model_ships_with_package_and_works_without_model_dir(tmp_path):
    runner = PretrainedPulse(str(tmp_path))
    assert runner.available("ma_ubfc_tscan")
    onnx, manifest = runner.paths("ma_ubfc_tscan")
    assert onnx == BUNDLED / "ma_ubfc_tscan.onnx"
    assert manifest == BUNDLED / "ma_ubfc_tscan.json"
    assert (BUNDLED / "LICENSE").is_file() and (BUNDLED / "NOTICE.md").is_file()


def test_bundled_model_matches_its_manifest_checksum():
    import hashlib
    import json

    manifest = json.loads((BUNDLED / "ma_ubfc_tscan.json").read_text(encoding="utf-8"))
    digest = hashlib.sha256((BUNDLED / "ma_ubfc_tscan.onnx").read_bytes()).hexdigest()
    assert digest == manifest["sha256"] == "404705f1cb0f986f6b373342e32e24c0b4c6798b2787e01fa955af63da11fe4d"


def test_user_model_dir_copy_takes_precedence(tmp_path):
    (tmp_path / "ubfc").mkdir()
    (tmp_path / "ubfc" / "ma_ubfc_tscan.onnx").write_bytes(b"local")
    (tmp_path / "ubfc" / "ma_ubfc_tscan.json").write_text("{}")
    onnx, manifest = PretrainedPulse(str(tmp_path)).paths("ma_ubfc_tscan")
    assert onnx == tmp_path / "ubfc" / "ma_ubfc_tscan.onnx"
    assert manifest == tmp_path / "ubfc" / "ma_ubfc_tscan.json"


def test_incomplete_user_copy_is_never_mixed_with_bundled_manifest(tmp_path):
    (tmp_path / "ubfc").mkdir()
    (tmp_path / "ubfc" / "ma_ubfc_tscan.onnx").write_bytes(b"local")
    onnx, manifest = PretrainedPulse(str(tmp_path)).paths("ma_ubfc_tscan")
    assert onnx.parent == manifest.parent


@pytest.mark.parametrize(
    "model_id", ["pure_efficientphys", "ubfc_efficientphys", "ubfc_tscan", "ubfc_physformer"]
)
def test_other_models_have_no_bundled_fallback(tmp_path, model_id):
    assert not PretrainedPulse(str(tmp_path)).available(model_id)


def test_api_reports_bundled_default_model_with_empty_model_dir(client, tmp_path):
    client.app.state.pretrained_pulse.directory = tmp_path
    body = client.get("/api/v1/pulse/model?model_id=ma_ubfc_tscan").json()
    assert body["available"] is True
    assert {m["id"]: m["available"] for m in body["models"]} == {
        "ma_ubfc_tscan": True,
        "pure_efficientphys": False,
        "ubfc_efficientphys": False,
        "ubfc_tscan": False,
        "ubfc_physformer": False,
    }


async def test_bundled_default_model_runs_inference_with_empty_model_dir(tmp_path):
    pytest.importorskip("onnxruntime")
    count = 91
    times = np.linspace(0, 3000, count, dtype="<f8")
    frames = np.random.default_rng(42).integers(40, 200, (count, 72, 72, 3), dtype=np.uint8)
    data = b"EP01" + struct.pack("<HH", count, 0) + times.tobytes() + frames.tobytes()
    runner = PretrainedPulse(str(tmp_path))
    result = await runner.infer(data, "ma_ubfc_tscan")
    assert result["model_id"] == "ma_ubfc_tscan"
    assert len(result["values"]) == 90
    assert np.isfinite(result["values"]).all()
    await runner.close()


def test_bundled_model_checksum_is_enforced(tmp_path, monkeypatch):
    import shutil

    import app.services.pretrained_pulse as module

    fake = tmp_path / "bundle"
    fake.mkdir()
    (fake / "ma_ubfc_tscan.onnx").write_bytes(b"tampered")
    shutil.copy(BUNDLED / "ma_ubfc_tscan.json", fake / "ma_ubfc_tscan.json")
    monkeypatch.setattr(module, "BUNDLED_PULSE_DIR", fake)
    runner = PretrainedPulse(str(tmp_path / "empty"))
    times = np.linspace(0, 3000, 91, dtype="<f8")
    frames = np.zeros((91, 72, 72, 3), dtype=np.uint8)
    with pytest.raises(ValueError, match="PULSE_MODEL_CHECKSUM_MISMATCH"):
        runner._run(times, frames, "ma_ubfc_tscan")


async def test_infer_refuses_to_load_while_the_realtime_models_are_stopped_for_a_break(
    tmp_path, monkeypatch
) -> None:
    from uuid import uuid4

    from app.ai.model_execution import ModelExecution
    from app.core.errors import AppError

    class Runtime:
        async def start(self) -> None:
            pass

        async def stop(self) -> None:
            pass

    execution = ModelExecution(Runtime())
    pulse = PretrainedPulse(str(tmp_path))
    pulse.execution = execution
    monkeypatch.setattr(pulse, "available", lambda *a: True)
    monkeypatch.setattr("app.services.pretrained_pulse.read_pulse_packet", lambda *a: (None, None))

    def load(*args):
        pulse.session = "ONNX"  # the lazy load of _run
        return {}

    monkeypatch.setattr(pulse, "_run", load)
    session = uuid4()
    await execution.start_session(session)
    await pulse.infer(b"x")  # round 1: fine
    await pulse.release()
    await execution.suspend_session(session)  # suspended, not yet borrowing
    with pytest.raises(AppError) as refused:
        await pulse.infer(b"x")
    assert refused.value.code == "INTERVIEW_BUSY" and pulse.session is None
    async with execution.borrowing(session):  # the generation model is loaded
        with pytest.raises(AppError):
            await pulse.infer(b"x")
        assert pulse.session is None
    await execution.resume_session(session)
    await pulse.infer(b"x")  # the realtime models are back
    assert pulse.session == "ONNX"
    await execution.stop_session(session)
