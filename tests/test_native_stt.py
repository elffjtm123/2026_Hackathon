import ctypes
from types import SimpleNamespace

import numpy as np
import pytest

from app.core.config import Settings


class Function:
    def __init__(self, call):
        self.call = call

    def __call__(self, *args):
        return self.call(*args)


class Library:
    def __init__(self):
        self.freed = []
        self.strings = []
        self.audio = None
        self.stop = 0
        self.status = 0
        self.text = "안녕하세요".encode()
        self.major = 3
        self.weight_type = b"Q8_0"
        self.name = b"Qwen3-ASR-0.6B"
        self.device = b"MTL0"
        self.architecture = b"qwen3-asr"
        self.speech_api_version_major = Function(lambda: self.major)
        self.speech_log_set = Function(lambda *_: None)
        self.speech_load_params_new = Function(lambda out: self.pointer(out, 1))
        self.speech_load_params_set_device = Function(lambda _, d: self.strings.append(d) or 0)
        self.speech_load_params_free = Function(lambda p: self.freed.append(p.value))
        self.speech_model_info_open = Function(lambda _, out: self.pointer(out, 2))
        self.speech_model_info_name = Function(lambda _: self.name)
        self.speech_model_info_architecture = Function(lambda _: self.architecture)
        self.speech_model_info_weight_type = Function(lambda _: self.weight_type)
        self.speech_model_info_device = Function(lambda _: self.device)
        self.speech_model_info_free = Function(lambda p: self.freed.append(p.value))
        self.speech_model_load = Function(lambda _, __, out: self.pointer(out, 3))
        self.speech_model_get_info = Function(lambda _, out: self.pointer(out, 4))
        self.speech_model_free = Function(lambda p: self.freed.append(p.value))
        self.speech_request_new = Function(lambda _, out: self.pointer(out, 5))
        self.speech_request_set_audio = Function(self.set_audio)
        self.speech_request_set_string = Function(
            lambda _, option, value: self.strings.append((option, value)) or 0
        )
        self.speech_transcribe = Function(lambda _: self.status)
        self.speech_request_result = Function(lambda _: 6)
        self.speech_result_stop = Function(lambda _: self.stop)
        self.speech_result_text = Function(lambda _: self.text)
        self.speech_request_free = Function(lambda p: self.freed.append(p.value))

    def pointer(self, out, value):
        ctypes.cast(out, ctypes.POINTER(ctypes.c_void_p))[0] = value
        return 0

    def set_audio(self, _, samples, count, rate):
        self.audio = (np.ctypeslib.as_array(samples, shape=(count,)).copy(), rate)
        return 0


@pytest.fixture
def engine(monkeypatch, tmp_path):
    from app.ai import native_stt

    library = Library()
    monkeypatch.setattr(native_stt.ctypes, "CDLL", lambda _: library)
    weights = tmp_path / "Qwen3-ASR-0.6B-Q8_0.gguf"
    weights.write_bytes(b"GGUF")
    loaded = native_stt.QwenGGUF(str(weights), "auto", "library")
    yield loaded, library
    loaded.close()


def test_default_stt_is_quantized_local_file():
    settings = Settings(_env_file=None)
    assert settings.stt_model == ".models/Qwen3-ASR-0.6B-Q8_0.gguf"
    assert settings.stt_library_path == ".models/speech/libspeech.dylib"


def test_stale_context_environment_cannot_reach_settings(monkeypatch):
    monkeypatch.setenv("STT_CONTEXT", "이전 참고 문구")
    assert "stt_context" not in Settings(_env_file=None).model_dump()


def test_native_transcription_has_no_context_and_frees_request(engine):
    loaded, library = engine
    audio = np.array([0.1, -0.2, 0.3], dtype=np.float64)
    text = loaded.transcribe(audio=(audio, 16000), language="Korean")
    assert text == "안녕하세요"
    assert loaded.device == "mps"
    assert (1, b"ko") in library.strings
    assert not any(isinstance(x, tuple) and x[0] == 9 for x in library.strings)
    assert library.audio[1] == 16000
    np.testing.assert_allclose(library.audio[0], audio)
    assert library.freed.count(5) == 1
    loaded.close()
    loaded.close()
    assert library.freed.count(3) == 1
    with pytest.raises(RuntimeError, match="STT_CLOSED"):
        loaded.transcribe(audio=(audio, 16000), language="Korean")


@pytest.mark.parametrize(
    "status,stop,text",
    [(-5, 0, b""), (1, 0, b""), (0, 2, b"partial"), (0, 0, None), (0, 0, b"\xff")],
)
def test_failed_truncated_or_invalid_result_is_not_a_transcript(engine, status, stop, text):
    loaded, library = engine
    library.status, library.stop, library.text = status, stop, text
    with pytest.raises((RuntimeError, UnicodeError)):
        loaded.transcribe(audio=(np.ones(1600), 16000), language="Korean")
    assert library.freed.count(5) == 1


@pytest.mark.parametrize(
    "field,value",
    [
        ("major", 2),
        ("weight_type", b"F16"),
        ("name", b"Qwen3-ASR-1.7B"),
        ("architecture", b"qwen3-tts"),
    ],
)
def test_wrong_abi_or_model_fails_before_loading_weights(monkeypatch, tmp_path, field, value):
    from app.ai import native_stt

    library = Library()
    setattr(library, field, value)
    monkeypatch.setattr(native_stt.ctypes, "CDLL", lambda _: library)
    model = tmp_path / "wrong.gguf"
    model.write_bytes(b"GGUF")
    with pytest.raises(RuntimeError):
        native_stt.QwenGGUF(str(model), "auto", "library")
    assert 3 not in library.freed


def test_adapter_close_waits_for_active_inference_before_freeing():
    from concurrent.futures import Future

    from app.ai.local_stt import LocalQwenSpeechAdapter

    calls = []
    future = Future()
    adapter = LocalQwenSpeechAdapter.__new__(LocalQwenSpeechAdapter)
    adapter.gate = SimpleNamespace(close=lambda: None, busy=True, future=future)
    adapter.stt = SimpleNamespace(close=lambda: calls.append("free"))
    adapter.close()
    assert calls == []
    future.set_result(None)
    assert calls == ["free"]
