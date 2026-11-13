"""Download only the selected public weights; never run downloads inside an API request."""

import argparse
import hashlib
import json
import os
import platform
import urllib.request
import zipfile
from pathlib import Path

from app.ai.experimental_stt import QWEN_FILES, ZIP_FILES

REPOS = {
    "qwen_q8": ("ggml-org/Qwen3-ASR-0.6B-GGUF", list(QWEN_FILES)),
    "whisper_small_int8": (
        "Systran/faster-whisper-small",
        [
            "model.bin",
            "config.json",
            "tokenizer.json",
            "vocabulary.*",
            "preprocessor_config.json",
        ],
    ),
    "whisper_base_int8": (
        "Systran/faster-whisper-base",
        [
            "model.bin",
            "config.json",
            "tokenizer.json",
            "vocabulary.*",
            "preprocessor_config.json",
        ],
    ),
    "zipformer_int8": (
        "k2-fsa/sherpa-onnx-streaming-zipformer-korean-2024-06-16",
        list(ZIP_FILES),
    ),
}


def prepare_llama(root: Path) -> dict:
    if os.name != "nt" or platform.machine().lower() not in {"amd64", "x86_64"}:
        raise RuntimeError(
            "자동 설치는 Windows x64 CPU용입니다. 다른 OS는 .models/stt/llama에 직접 설치하세요."
        )
    request = urllib.request.Request(
        "https://api.github.com/repos/ggml-org/llama.cpp/releases/latest",
        headers={"User-Agent": "local-stt-experiment"},
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        release = json.load(response)
    if not any(a["name"].endswith("bin-win-cpu-x64.zip") for a in release["assets"]):
        # Stable releases can be pointers to a tested nightly instead of binary bundles.
        pointer = next(a for a in release["assets"] if a["name"] == "nightly-tag.txt")
        with urllib.request.urlopen(pointer["browser_download_url"], timeout=30) as response:
            tag = response.read().decode().strip()
        if not tag.startswith("b") or not tag[1:].isdigit():
            raise RuntimeError("알 수 없는 llama.cpp 릴리스 포인터")
        request = urllib.request.Request(
            f"https://api.github.com/repos/ggml-org/llama.cpp/releases/tags/{tag}",
            headers={"User-Agent": "local-stt-experiment"},
        )
        with urllib.request.urlopen(request, timeout=30) as response:
            release = json.load(response)
    asset = next(a for a in release["assets"] if a["name"].endswith("bin-win-cpu-x64.zip"))
    directory = root / "llama" / release["tag_name"]
    directory.mkdir(parents=True, exist_ok=True)
    archive = directory / asset["name"]
    if not archive.exists():
        print(f"llama.cpp {release['tag_name']} CPU runtime download", flush=True)
        urllib.request.urlretrieve(asset["browser_download_url"], archive)
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    expected = asset.get("digest")
    if expected and expected != f"sha256:{digest}":
        raise RuntimeError("llama.cpp ZIP 체크섬 불일치")
    with zipfile.ZipFile(archive) as bundle:
        for member in bundle.infolist():
            target = (directory / member.filename).resolve()
            if not target.is_relative_to(directory.resolve()):
                raise RuntimeError("안전하지 않은 ZIP 경로")
        bundle.extractall(directory)
    return {"release": release["tag_name"], "asset": asset["name"], "sha256": digest}


def main() -> None:
    from huggingface_hub import HfApi, snapshot_download

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--models", nargs="+", choices=list(REPOS), default=list(REPOS))
    parser.add_argument("--root", type=Path, default=Path(".models/stt"))
    parser.add_argument("--llama", action="store_true", help="공식 Windows CPU 실행 파일도 설치")
    args = parser.parse_args()
    args.root.mkdir(parents=True, exist_ok=True)
    manifest_path = args.root / "manifest.json"
    manifest = (
        json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.exists() else {}
    )
    for model_id in args.models:
        repo, patterns = REPOS[model_id]
        revision = HfApi().model_info(repo).sha
        print(f"Preparing {model_id}: {repo}@{revision}", flush=True)
        snapshot_download(
            repo,
            revision=revision,
            allow_patterns=patterns,
            local_dir=args.root / model_id,
            max_workers=2,
        )
        manifest[model_id] = {
            "repository": repo,
            "revision": revision,
            "quantization": "runtime INT8" if model_id.startswith("whisper") else "published",
        }
        manifest_path.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    if args.llama:
        manifest["llama"] = prepare_llama(args.root)
        manifest_path.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    print("모델 준비 완료. 화면에서 상태 새로고침 후 실행하세요.", flush=True)


if __name__ == "__main__":
    main()
