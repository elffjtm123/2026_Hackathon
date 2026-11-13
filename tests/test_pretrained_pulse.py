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
