"""CPU-only experiment engines. No downloads or model fallback during inference."""

import importlib.util
import io
import os
import re
import socket
import subprocess
import time
import wave
from pathlib import Path
from typing import Any

import httpx

MODEL_IDS = (
    "service_qwen",
    "qwen_q8",
    "whisper_small_int8",
    "whisper_base_int8",
    "zipformer_int8",
)
LABELS = {
    "service_qwen": "현재 서비스 · Qwen3-ASR-0.6B Q8_0 (speech.cpp)",
    "qwen_q8": "Qwen3-ASR-0.6B · Q8_0",
    "whisper_small_int8": "Whisper small · INT8",
    "whisper_base_int8": "Whisper base · INT8",
    "zipformer_int8": "한국어 Zipformer · INT8",
}
ZIP_FILES = (
    "encoder-epoch-99-avg-1.int8.onnx",
    "decoder-epoch-99-avg-1.onnx",
    "joiner-epoch-99-avg-1.int8.onnx",
    "tokens.txt",
)
QWEN_FILES = ("Qwen3-ASR-0.6B-Q8_0.gguf", "mmproj-Qwen3-ASR-0.6B-Q8_0.gguf")


def llama_binary(root: Path) -> Path | None:
    name = "llama-server.exe" if os.name == "nt" else "llama-server"
    return next((p for p in (root / "llama").rglob(name) if p.is_file()), None)


def catalog(root: Path, speech: Any) -> list[dict[str, Any]]:
    result = []
    for model_id in MODEL_IDS:
        missing = []
        if model_id == "service_qwen":
            if hasattr(speech, "reason"):
                missing.append(str(speech.reason))
            elif hasattr(speech, 'owner'):
                settings = speech.owner.settings
                for path in (settings.stt_model, settings.stt_library_path):
                    if not Path(path).is_file():
                        missing.append(path)
            elif getattr(speech, "device", None) != "cpu":
                missing.append("CPU 비교를 위해 서비스 STT_DEVICE=cpu 설정이 필요합니다.")
        else:
            module = "sherpa_onnx" if model_id == "zipformer_int8" else "faster_whisper"
            if model_id != "qwen_q8" and importlib.util.find_spec(module) is None:
                missing.append(f"{module} 패키지 설치 필요")
            files = ZIP_FILES if model_id == "zipformer_int8" else QWEN_FILES
            if model_id.startswith("whisper_"):
                files = ("model.bin", "config.json", "tokenizer.json")
            for filename in files:
                if not (root / model_id / filename).is_file():
                    missing.append(filename)
            if model_id == "qwen_q8" and llama_binary(root) is None:
                missing.append("llama-server 실행 파일")
        result.append(
            {
                "id": model_id,
                "label": LABELS[model_id],
                "available": not missing,
                "reason": "준비됨 (실제 로딩은 실행 시 검증)"
                if not missing
                else " / ".join(missing),
            }
        )
    return result


def wav_bytes(pcm: bytes) -> bytes:
    output = io.BytesIO()
    with wave.open(output, "wb") as stream:
        stream.setnchannels(1)
        stream.setsampwidth(2)
        stream.setframerate(16000)
        stream.writeframes(pcm)
    return output.getvalue()


def clean_qwen_text(text: str) -> str:
    if "<asr_text>" in text:
        text = text.split("<asr_text>", 1)[1]
    return re.sub(r"<\|[^>]+\|>", "", text).strip()


class WhisperEngine:
    def __init__(self, path: Path, threads: int, context: str) -> None:
        from faster_whisper import WhisperModel

        self.model = WhisperModel(
            str(path),
            device="cpu",
            compute_type="int8",
            cpu_threads=threads,
            num_workers=1,
            local_files_only=True,
        )
        self.context = context
        self.metadata = {"engine": "faster-whisper", "precision": "int8", "beam_size": 5}

    def transcribe(self, audio: Any) -> str:
        segments, _ = self.model.transcribe(
            audio,
            language="ko",
            beam_size=5,
            temperature=0,
            initial_prompt=self.context or None,
            condition_on_previous_text=False,
            vad_filter=False,
        )
        return " ".join(segment.text.strip() for segment in segments).strip()

    def close(self) -> None:
        del self.model


class ZipformerEngine:
    def __init__(self, path: Path, threads: int) -> None:
        import sherpa_onnx

        self.model = sherpa_onnx.OnlineRecognizer.from_transducer(
            tokens=str(path / ZIP_FILES[3]),
            encoder=str(path / ZIP_FILES[0]),
            decoder=str(path / ZIP_FILES[1]),
            joiner=str(path / ZIP_FILES[2]),
            num_threads=threads,
            sample_rate=16000,
            feature_dim=80,
            decoding_method="greedy_search",
            provider="cpu",
            enable_endpoint_detection=False,
        )
        self.metadata = {
            "engine": "sherpa-onnx",
            "precision": "encoder/joiner int8; decoder fp32",
            "decoding": "greedy_search",
            "context_supported": False,
            "stream_policy": "reset_per_chunk_for_service_parity",
        }

    def transcribe(self, audio: Any) -> str:
        import numpy as np

        stream = self.model.create_stream()
        stream.accept_waveform(16000, audio)
        # Required transducer right context, not part of measured audio duration.
        stream.accept_waveform(16000, np.zeros(4800, dtype=np.float32))
        stream.input_finished()
        while self.model.is_ready(stream):
            self.model.decode_stream(stream)
        return self.model.get_result(stream).strip()

    def close(self) -> None:
        del self.model


class QwenQ8Engine:
    """Own a loopback llama.cpp process and stop only that process on close."""

    def __init__(self, root: Path, threads: int, context: str) -> None:
        binary = llama_binary(root)
        if binary is None:
            raise RuntimeError("llama-server가 없습니다. 모델 준비 스크립트를 실행하세요.")
        path = root / "qwen_q8"
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        self.client = httpx.Client(base_url=f"http://127.0.0.1:{port}", timeout=180)
        self.context = context
        self.process = subprocess.Popen(
            [
                str(binary.resolve()),
                "-m",
                str((path / QWEN_FILES[0]).resolve()),
                "--mmproj",
                str((path / QWEN_FILES[1]).resolve()),
                "--host",
                "127.0.0.1",
                "--port",
                str(port),
                "--threads",
                str(threads),
                "--threads-batch",
                str(threads),
                "--device",
                "none",
                "--gpu-layers",
                "0",
                "--no-mmproj-offload",
                "--ctx-size",
                "4096",
                "--parallel",
                "1",
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
        self.metadata = {"engine": "llama.cpp", "precision": "Q8_0 + Q8_0 mmproj"}
        try:
            deadline = time.monotonic() + 180
            while time.monotonic() < deadline:
                if self.process.poll() is not None:
                    raise RuntimeError(
                        "llama-server 모델 로딩 실패: 실행 버전과 GGUF를 확인하세요."
                    )
                try:
                    if self.client.get("/health", timeout=1).status_code == 200:
                        return
                except httpx.HTTPError:
                    pass
                time.sleep(0.25)
            raise RuntimeError("llama-server 준비 시간 초과 (180초)")
        except BaseException:
            self.close()
            raise

    def transcribe(self, audio: Any) -> str:
        import base64

        import numpy as np

        pcm = np.clip(audio * 32768, -32768, 32767).astype("<i2").tobytes()
        response = self.client.post(
            "/v1/chat/completions",
            json={
                "messages": [
                    {"role": "system", "content": self.context},
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "input_audio",
                                "input_audio": {
                                    "data": base64.b64encode(wav_bytes(pcm)).decode(),
                                    "format": "wav",
                                },
                            }
                        ],
                    },
                    {"role": "assistant", "content": "language Korean<asr_text>"},
                ],
                "temperature": 0,
                "max_tokens": 128,
                "stream": False,
                "cache_prompt": False,
            },
        )
        response.raise_for_status()
        body = response.json()
        if body.get("choices", [{}])[0].get("finish_reason") == "length":
            raise RuntimeError("Qwen Q8 출력이 토큰 한도에 도달했습니다. 청크를 줄이세요.")
        content = body["choices"][0]["message"].get("content")
        if not isinstance(content, str):
            raise RuntimeError("Qwen Q8 전사 응답 형식이 올바르지 않습니다.")
        return clean_qwen_text(content)

    def close(self) -> None:
        if self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=5)
        self.client.close()


def create_engine(model_id: str, root: Path, threads: int, context: str) -> Any:
    if model_id.startswith("whisper_"):
        return WhisperEngine(root / model_id, threads, context)
    if model_id == "zipformer_int8":
        return ZipformerEngine(root / model_id, threads)
    if model_id == "qwen_q8":
        return QwenQ8Engine(root, threads, context)
    raise ValueError("알 수 없는 실험 모델")
