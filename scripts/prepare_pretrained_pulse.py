"""Export official PURE EfficientPhys weights for bounded local CPU inference."""

import argparse
import hashlib
import importlib.util
import json
import copy
import types
from pathlib import Path
from unittest.mock import patch

import numpy as np
import torch

ROOT = Path(__file__).resolve().parents[1]
DIRECTORY = ROOT / ".models/pulse"
REVISION = "b7500b848f84ad7f86e277b4612563b69f4f88f9"
SOURCE_HASHES = {
    "EfficientPhys.py": "384b01b5c99d6d280b5ddb9e2358631f89747e40e3181b6a174e26d6e74798c9",
    "PURE_EfficientPhys.pth": "e65a962e07bcac32a668e6acb9f8ed43cdb1b01cfb97262654dc5b55c0cf3a49",
}


def main() -> None:
    import onnxruntime as ort

    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--download", action="store_true", help="Download pinned official files only"
    )
    args = parser.parse_args()
    DIRECTORY.mkdir(parents=True, exist_ok=True)
    if args.download:
        import httpx

        sources = {
            "EfficientPhys.py": "neural_methods/model/EfficientPhys.py",
            "PURE_EfficientPhys.pth": "final_model_release/PURE_EfficientPhys.pth",
            "LICENSE": "LICENSE",
        }
        with httpx.Client(follow_redirects=True, timeout=120) as client:
            for name, relative in sources.items():
                target = DIRECTORY / name
                if target.exists():
                    continue
                response = client.get(
                    f"https://raw.githubusercontent.com/ubicomplab/rPPG-Toolbox/{REVISION}/{relative}"
                )
                response.raise_for_status()
                expected = SOURCE_HASHES.get(name)
                if expected and hashlib.sha256(response.content).hexdigest() != expected:
                    raise ValueError(f"Official source checksum mismatch: {name}")
                target.write_bytes(response.content)
    for name, expected in SOURCE_HASHES.items():
        if hashlib.sha256((DIRECTORY / name).read_bytes()).hexdigest() != expected:
            raise ValueError(f"Pinned source checksum mismatch: {name}; original file retained")
    torch.set_num_threads(2)
    spec = importlib.util.spec_from_file_location(
        "official_efficientphys", DIRECTORY / "EfficientPhys.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    model = module.EfficientPhys(frame_depth=10, img_size=72).eval()
    state = torch.load(DIRECTORY / "PURE_EfficientPhys.pth", map_location="cpu", weights_only=True)
    state = {key.removeprefix("module."): value for key, value in state.items()}
    model.load_state_dict(state, strict=True)
    torch.manual_seed(42)
    example = torch.randn(91, 3, 72, 72)
    target = DIRECTORY / "EfficientPhys-PURE-91.onnx"
    export_model = copy.deepcopy(model)

    def shift_without_scatter(layer, x):
        nt, channels, height, width = x.shape
        x = x.reshape(nt // layer.n_segment, layer.n_segment, channels, height, width)
        fold = channels // layer.fold_div
        left = torch.cat((x[:, 1:, :fold], x[:, :1, :fold] * 0), dim=1)
        right = torch.cat((x[:, :1, fold : 2 * fold] * 0, x[:, :-1, fold : 2 * fold]), dim=1)
        return torch.cat((left, right, x[:, :, 2 * fold :]), dim=2).reshape(
            nt, channels, height, width
        )

    for layer in export_model.modules():
        if isinstance(layer, module.TSM):
            layer.forward = types.MethodType(shift_without_scatter, layer)
    # ONNX legacy export lacks aten::diff; use equivalent adjacent subtraction
    # during export only, and verify against the untouched original afterwards.
    with patch("torch.diff", side_effect=lambda x, dim=0: x[1:] - x[:-1]):
        torch.onnx.export(
            export_model,
            example,
            str(target),
            input_names=["frames"],
            output_names=["pulse_derivative"],
            opset_version=17,
            dynamo=False,
        )
    options = ort.SessionOptions()
    options.intra_op_num_threads = 2
    options.inter_op_num_threads = 1
    session = ort.InferenceSession(
        str(target), sess_options=options, providers=["CPUExecutionProvider"]
    )
    with torch.inference_mode():
        expected = model(example).numpy()
    actual = session.run(None, {"frames": example.numpy()})[0]
    np.testing.assert_allclose(actual, expected, rtol=1e-3, atol=1e-4)
    files = ["EfficientPhys.py", "PURE_EfficientPhys.pth", "EfficientPhys-PURE-91.onnx", "LICENSE"]
    manifest = {
        "model": "EfficientPhys",
        "training_dataset": "PURE",
        "source_revision": REVISION,
        "source_repository": "https://github.com/ubicomplab/rPPG-Toolbox",
        "license": "Responsible AI Source Code License 1.1",
        "input": [91, 3, 72, 72],
        "output_frames": 90,
        "nominal_fps": 30,
        "pytorch_version": torch.__version__,
        "files": {
            name: {
                "bytes": (DIRECTORY / name).stat().st_size,
                "sha256": hashlib.sha256((DIRECTORY / name).read_bytes()).hexdigest(),
            }
            for name in files
        },
    }
    (DIRECTORY / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(
        json.dumps(
            {
                "verified": True,
                "max_absolute_error": float(np.max(np.abs(actual - expected))),
                "onnx_bytes": target.stat().st_size,
            }
        )
    )


if __name__ == "__main__":
    main()
