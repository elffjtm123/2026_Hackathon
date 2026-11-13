"""Verify pinned UBFC weights and export three official architectures (no training)."""
import copy
import hashlib
import importlib.util
import json
import types
from pathlib import Path
from unittest.mock import patch

import numpy as np
import onnxruntime as ort
import torch

ROOT = Path(__file__).resolve().parents[1] / '.models/pulse/ubfc'
REVISION = 'b7500b848f84ad7f86e277b4612563b69f4f88f9'
HASHES = {
    'EfficientPhys.py': '384b01b5c99d6d280b5ddb9e2358631f89747e40e3181b6a174e26d6e74798c9',
    'TS_CAN.py': '987b7e39be59016b136fc71c146b5a71ba1b22d28695fb1cfe6a7307f6dd5ce1',
    'PhysFormer.py': 'da33e0195d2148cadcd68c6f3ea3eb6a22b94b49f5ec8b086339b1c1b93bc314',
    'UBFC-rPPG_EfficientPhys.pth': '219b970e04b3580ee4c063554b7d9fe2a7a3ceb4e9e585980f15ac8313054cd6',
    'UBFC-rPPG_TSCAN.pth': '3c087279861a6312bbe770b348c7609f30cb5b5bb7ced7fa446caebf072196e3',
    'MA-UBFC_tscan.pth': 'f751d6fdd264dc75ee5d3e937a9a20fa651e4b83dfdd2dee875247a1f86c9adb',
    'UBFC-rPPG_PhysFormer_DiffNormalized.pth': '4f2b0ed8a270f1687b275ace05b6ca0ced8d91f227bd3c3f0d584d16d0d4b02e',
    'LICENSE': 'a2d16c386a18fc6c88ce0ff9d4593082f74a041c96e92ca9e2d89731955f1e1c',
}

def load(name):
    spec = importlib.util.spec_from_file_location('official_' + name, ROOT / (name + '.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

def shift(layer, x):
    nt, c, h, w = x.shape
    x = x.reshape(nt // layer.n_segment, layer.n_segment, c, h, w)
    fold = c // layer.fold_div
    a = torch.cat((x[:, 1:, :fold], x[:, :1, :fold] * 0), 1)
    b = torch.cat((x[:, :1, fold:2*fold] * 0, x[:, :-1, fold:2*fold]), 1)
    return torch.cat((a, b, x[:, :, 2*fold:]), 2).reshape(nt, c, h, w)

class PhysOutput(torch.nn.Module):
    def __init__(self, model):
        super().__init__()
        self.model = model
    def forward(self, frames):
        return self.model(frames, 2.0)[0]

def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--download', action='store_true')
    parser.add_argument('--model', default='all')
    args = parser.parse_args()
    ROOT.mkdir(parents=True, exist_ok=True)
    for name, digest in HASHES.items():
        p = ROOT / name
        if not p.exists() and args.download:
            import urllib.request
            relative = 'LICENSE' if name == 'LICENSE' else ('neural_methods/model/' if name.endswith('.py') else 'final_model_release/') + name
            p.write_bytes(urllib.request.urlopen(f'https://raw.githubusercontent.com/ubicomplab/rPPG-Toolbox/{REVISION}/{relative}', timeout=120).read())
        if hashlib.sha256(p.read_bytes()).hexdigest() != digest:
            raise ValueError('Pinned checksum mismatch: ' + name)
    torch.set_num_threads(2)
    torch.manual_seed(42)
    efficient, tscan, phys = load('EfficientPhys'), load('TS_CAN'), load('PhysFormer')
    definitions = [
        ('ma_ubfc_tscan', tscan.TSCAN(frame_depth=10, img_size=72), 'MA-UBFC_tscan.pth', (90,6,72,72)),
        ('ubfc_efficientphys', efficient.EfficientPhys(frame_depth=10, img_size=72), 'UBFC-rPPG_EfficientPhys.pth', (91,3,72,72)),
        ('ubfc_tscan', tscan.TSCAN(frame_depth=10, img_size=72), 'UBFC-rPPG_TSCAN.pth', (90,6,72,72)),
        ('ubfc_physformer', phys.ViT_ST_ST_Compact3_TDC_gra_sharp(image_size=(160,128,128), patches=(4,4,4), dim=96, ff_dim=144, num_heads=4, num_layers=12, dropout_rate=0.1, theta=0.7), 'UBFC-rPPG_PhysFormer_DiffNormalized.pth', (1,3,160,128,128)),
    ]
    for model_id, model, weights, shape in definitions:
        if args.model != 'all' and args.model != model_id: continue
        state = torch.load(ROOT / weights, map_location='cpu', weights_only=True)
        model.load_state_dict({k.removeprefix('module.'): v for k,v in state.items()}, strict=True)
        model.eval()
        reference = PhysOutput(model) if model_id == 'ubfc_physformer' else model
        exported = copy.deepcopy(reference)
        for layer in exported.modules():
            if type(layer).__name__ == 'TSM':
                layer.forward = types.MethodType(shift, layer)
        example = torch.randn(shape)
        path = ROOT / (model_id + '.onnx')
        with patch('torch.diff', side_effect=lambda x, dim=0: x[1:] - x[:-1]):
            torch.onnx.export(exported, example, str(path), input_names=['frames'], output_names=['pulse_derivative'], opset_version=17, dynamo=False)
        options = ort.SessionOptions(); options.intra_op_num_threads = 2; options.inter_op_num_threads = 1
        session = ort.InferenceSession(str(path), sess_options=options, providers=['CPUExecutionProvider'])
        with torch.inference_mode(): expected = reference(example).numpy()
        actual = session.run(None, {'frames': example.numpy()})[0]
        np.testing.assert_allclose(actual, expected, rtol=1e-3, atol=1e-4)
        manifest = {'model_id':model_id, 'training_dataset':'Motion-augmented UBFC-rPPG' if model_id.startswith('ma_') else 'UBFC-rPPG', 'source_revision':REVISION,
            'input':shape, 'source_hashes':HASHES, 'sha256':hashlib.sha256(path.read_bytes()).hexdigest(),
            'bytes':path.stat().st_size, 'max_export_error':float(np.max(np.abs(actual-expected)))}
        path.with_suffix('.json').write_text(json.dumps(manifest, indent=2), encoding='utf-8')
        print(json.dumps(manifest), flush=True)

if __name__ == '__main__': main()
