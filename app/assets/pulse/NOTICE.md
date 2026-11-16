# Bundled rPPG pulse model

- `ma_ubfc_tscan.onnx`: TS-CAN weights `MA-UBFC_tscan.pth` (trained on Motion-augmented UBFC-rPPG)
  from [ubicomplab/rPPG-Toolbox](https://github.com/ubicomplab/rPPG-Toolbox), pinned revision
  `b7500b848f84ad7f86e277b4612563b69f4f88f9`.
- Converted to ONNX without retraining by `scripts/prepare_ubfc_pulse.py`. `ma_ubfc_tscan.json` records
  the source hashes and the ONNX `sha256`, which the backend checks before loading the model.
- License: Responsible AI License 1.1 (`LICENSE`, copied unchanged from the source revision).
  Use is subject to the use restrictions in Section 3.2, including the restriction on detecting or
  inferring health and medical conditions. Anyone who distributes or deploys this model must pass the
  Section 3.2 restrictions on to their users as enforceable terms (Section 3.3).
