"""Qwen3-ASR Q8_0 through speech.cpp's versioned C API, in the realtime worker."""

import ctypes
from pathlib import Path
from typing import Any


class QwenGGUF:
    def __init__(self, model_path: str, device: str, library_path: str) -> None:
        if not Path(model_path).is_file():
            raise RuntimeError("STT_MODEL_NOT_FOUND")
        self.lib = ctypes.CDLL(str(Path(library_path).resolve()))
        self.lib.speech_api_version_major.argtypes = []
        self.lib.speech_api_version_major.restype = ctypes.c_int
        if self.lib.speech_api_version_major() != 3:
            raise RuntimeError("STT_LIBRARY_ABI_MISMATCH")
        pointer, string, integer = ctypes.c_void_p, ctypes.c_char_p, ctypes.c_int
        out = ctypes.POINTER(pointer)
        signatures = {
            "speech_log_set": ([pointer, pointer], None),
            "speech_load_params_new": ([out], integer),
            "speech_load_params_set_device": ([pointer, string], integer),
            "speech_load_params_free": ([pointer], None),
            "speech_model_info_open": ([string, out], integer),
            "speech_model_info_name": ([pointer], string),
            "speech_model_info_architecture": ([pointer], string),
            "speech_model_info_weight_type": ([pointer], string),
            "speech_model_info_device": ([pointer], string),
            "speech_model_info_free": ([pointer], None),
            "speech_model_load": ([string, pointer, out], integer),
            "speech_model_get_info": ([pointer, out], integer),
            "speech_model_free": ([pointer], None),
            "speech_request_new": ([pointer, out], integer),
            "speech_request_set_audio": (
                [pointer, ctypes.POINTER(ctypes.c_float), ctypes.c_size_t, integer],
                integer,
            ),
            "speech_request_set_string": ([pointer, integer, string], integer),
            "speech_transcribe": ([pointer], integer),
            "speech_request_result": ([pointer], pointer),
            "speech_result_stop": ([pointer], integer),
            "speech_result_text": ([pointer], string),
            "speech_request_free": ([pointer], None),
        }
        for name, (arguments, result) in signatures.items():
            function = getattr(self.lib, name)
            function.argtypes, function.restype = arguments, result
        self.lib.speech_log_set(None, None)  # Native logs must never expose recognized text.
        self.model = pointer()
        info, params = pointer(), pointer()
        try:
            self._check(self.lib.speech_model_info_open(model_path.encode(), ctypes.byref(info)))
            if (
                self.lib.speech_model_info_name(info) != b"Qwen3-ASR-0.6B"
                or self.lib.speech_model_info_architecture(info) != b"qwen3-asr"
                or self.lib.speech_model_info_weight_type(info) != b"Q8_0"
            ):
                raise RuntimeError("STT_EXPECTED_QWEN_06B_Q8_0")
            self.lib.speech_model_info_free(info)
            info = pointer()
            self._check(self.lib.speech_load_params_new(ctypes.byref(params)))
            native_device = "MTL0" if device == "mps" else device
            self._check(self.lib.speech_load_params_set_device(params, native_device.encode()))
            self._check(
                self.lib.speech_model_load(model_path.encode(), params, ctypes.byref(self.model))
            )
            self._check(self.lib.speech_model_get_info(self.model, ctypes.byref(info)))
            selected = (self.lib.speech_model_info_device(info) or b"").decode("utf-8")
            if selected.upper().startswith("MTL"):
                self.device = "mps"
            elif selected.upper() == "CPU":
                self.device = "cpu"
            else:
                raise RuntimeError("STT_UNSUPPORTED_DEVICE")
        except BaseException:
            self.close()
            raise
        finally:
            self.lib.speech_model_info_free(info)
            self.lib.speech_load_params_free(params)

    @staticmethod
    def _check(status: int) -> None:
        if status != 0:
            raise RuntimeError(f"STT_NATIVE_FAILED:{status}")

    def transcribe(self, *, audio: tuple[Any, int], context: str, language: str) -> str:
        import numpy as np

        if not self.model.value:
            raise RuntimeError("STT_CLOSED")
        samples, rate = audio
        samples = np.ascontiguousarray(samples, dtype=np.float32)
        if samples.ndim != 1 or samples.size == 0 or rate <= 0:
            raise ValueError("STT_INVALID_AUDIO")
        request = ctypes.c_void_p()
        try:
            self._check(self.lib.speech_request_new(self.model, ctypes.byref(request)))
            self._check(
                self.lib.speech_request_set_audio(
                    request,
                    samples.ctypes.data_as(ctypes.POINTER(ctypes.c_float)),
                    samples.size,
                    rate,
                )
            )
            self._check(
                self.lib.speech_request_set_string(
                    request, 1, ("ko" if language == "Korean" else language).encode()
                )
            )
            self._check(self.lib.speech_request_set_string(request, 9, context.encode()))
            self._check(self.lib.speech_transcribe(request))
            result = self.lib.speech_request_result(request)
            if not result or self.lib.speech_result_stop(result) != 0:
                raise RuntimeError("STT_INCOMPLETE_RESULT")
            text = self.lib.speech_result_text(result)
            if text is None:
                raise RuntimeError("STT_INVALID_RESULT")
            return text.decode("utf-8")
        finally:
            self.lib.speech_request_free(request)

    def close(self) -> None:
        if self.model.value:
            self.lib.speech_model_free(self.model)
            self.model = ctypes.c_void_p()
