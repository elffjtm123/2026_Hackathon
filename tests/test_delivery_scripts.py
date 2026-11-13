import csv
import json
import math
from pathlib import Path

import numpy as np
import pytest
import soundfile

from scripts.experiment_delivery import run_experiment
from scripts.extract_delivery_features import extract_features, main


def write_wav(path: Path, voiced_s: float, quiet_s: float, rate=44_100, channels=2):
    t = np.arange(int(voiced_s * rate)) / rate
    tone = 0.3 * np.sin(2 * math.pi * 200 * t)
    data = np.concatenate([tone, np.zeros(int(quiet_s * rate))])
    soundfile.write(path, np.stack([data] * channels, axis=1), rate)


def write_manifest(tmp_path: Path) -> Path:
    write_wav(tmp_path / "a.wav", 2.0, 1.0)
    write_wav(tmp_path / "b.wav", 0.5, 0.5, rate=16_000, channels=1)
    path = tmp_path / "manifest.csv"
    with path.open("w", encoding="utf-8", newline="") as file:
        writer = csv.writer(file)
        writer.writerow(["utterance_id", "speaker_id", "wav_path", "transcript", "delivery"])
        writer.writerow(["u1", "s1", "a.wav", "안녕하세요 음 저는", "4"])
        writer.writerow(["u2", "s2", str(tmp_path / "b.wav"), "네", "2"])
    return path


def read(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as file:
        return list(csv.DictReader(file))


def loud(pcm: bytes) -> bool:
    samples = np.frombuffer(pcm, dtype="<i2").astype(float) / 32768
    return float(np.sqrt(np.mean(samples**2))) > 0.05


def test_extract_features_resamples_and_passes_labels_through(tmp_path):
    out = tmp_path / "features.csv"
    extract_features(
        write_manifest(tmp_path),
        out,
        is_speech=loud,
        extract_f0=lambda pcm: [(100, 100.0), (200, 200.0)],
    )
    first, second = read(out)
    assert (first["utterance_id"], first["speaker_id"], first["delivery"]) == ("u1", "s1", "4")
    assert abs(int(first["voiced_ms"]) - 2000) <= 40
    assert first["syllables"] == "8"
    assert float(first["disfluency_density"]) == pytest.approx(60_000 / int(first["voiced_ms"]))
    assert float(first["pvq"]) == pytest.approx(1 / 3)
    assert first["sentence_end_pause_ms"] == ""
    assert float(first["speech_rate"]) == pytest.approx(
        8 * 60_000 / int(first["voiced_ms"]), rel=0.1
    )
    assert float(first["f0_median_hz"]) == pytest.approx(150)
    assert float(first["f0_st"]) == pytest.approx(0)
    assert float(first["alpha_ratio_db"]) > 20
    assert "hammarberg_db" in first
    assert first["short_voiced"] == "0"
    assert second["short_voiced"] == "1"
    assert second["utterance_id"] == "u2"


def test_windows_out_writes_one_row_per_window_per_utterance(tmp_path):
    out, windows_out = tmp_path / "features.csv", tmp_path / "windows.csv"
    extract_features(
        write_manifest(tmp_path),
        out,
        windows_out=windows_out,
        is_speech=loud,
        extract_f0=lambda pcm: [(100, 100.0), (200, 200.0)],
    )
    rows = read(windows_out)
    assert [(x["utterance_id"], x["speaker_id"], x["window_index"]) for x in rows] == [
        ("u1", "s1", "0"),
        ("u2", "s2", "0"),
    ]
    first = rows[0]
    assert (first["start_ms"], first["end_ms"]) == ("0", "10000")
    assert abs(int(first["voiced_ms"]) - 2000) <= 40
    observed = int(first["observed_ms"])
    assert 0 < observed < 10_000
    assert float(first["coverage"]) == pytest.approx(int(first["voiced_ms"]) / observed)
    assert float(first["speech_rate"]) == pytest.approx(8 * 60_000 / observed)
    assert rows[1]["speech_rate"] == ""
    assert rows[1]["f0_median_hz"] == ""


def test_cli_accepts_windows_out(tmp_path):
    windows_out = tmp_path / "windows.csv"
    main(
        [
            "--manifest", str(write_manifest(tmp_path)),
            "--out", str(tmp_path / "features.csv"),
            "--windows-out", str(windows_out),
        ]
    )  # fmt: skip
    assert len(read(windows_out)) == 2


def test_cli_runs_with_the_real_vad_and_f0(tmp_path):
    out = tmp_path / "features.csv"
    main(["--manifest", str(write_manifest(tmp_path)), "--out", str(out)])
    assert [x["utterance_id"] for x in read(out)] == ["u1", "u2"]


def synthetic_features(tmp_path: Path) -> Path:
    rng = np.random.default_rng(0)
    path = tmp_path / "features.csv"
    names = ["voiced_ms", "articulation_rate", "pause_count", "disfluency_density", "pvq"]
    with path.open("w", encoding="utf-8", newline="") as file:
        writer = csv.writer(file)
        writer.writerow(["utterance_id", "speaker_id", *names, "delivery"])
        for index in range(200):
            x = rng.normal(size=5)
            target = float(np.clip(2.5 + 1.0 * x[4] + rng.normal(scale=0.3), 0.0, 5.0))
            writer.writerow([f"u{index}", f"s{index % 20}", *x, round(target, 2)])
        writer.writerow(["bad1", "s0", *rng.normal(size=5), ""])
        writer.writerow(["bad2", "s1", *rng.normal(size=5), "9"])
    return path


def test_experiment_full_model_beats_mean_baseline_and_recovers_sign(tmp_path):
    result = run_experiment(
        synthetic_features(tmp_path),
        target="delivery",
        group="speaker_id",
        target_range=(0.0, 5.0),
        binary_threshold=2.5,
        bootstrap=100,
    )
    assert result["n_rows"] == 200
    models = result["models"]
    assert models["full"]["rmse"]["value"] < models["mean"]["rmse"]["value"]
    assert models["full"]["pearson"]["value"] > 0.9
    assert models["full"]["auc"]["value"] > 0.9
    assert models["mean"]["auc"]["value"] is None
    assert result["coefficients"]["pvq"] > 0.5
    assert set(models) == {"mean", "voiced_ms", "articulation_rate", "full"}


def test_experiment_cli_writes_json(tmp_path, capsys):
    from scripts.experiment_delivery import main as experiment_main

    out = tmp_path / "result.json"
    experiment_main(
        [
            "--features", str(synthetic_features(tmp_path)),
            "--target", "delivery",
            "--target-range", "0", "5",
            "--bootstrap", "50",
            "--out-json", str(out),
        ]
    )  # fmt: skip
    assert "full" in capsys.readouterr().out
    assert json.loads(out.read_text())["models"]["full"]["rmse"]["value"] > 0


def few_group_features(tmp_path: Path) -> Path:
    path = synthetic_features(tmp_path)
    rows = read(path)
    with path.open("w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=list(rows[0]))
        writer.writeheader()
        for row in rows:
            writer.writerow({**row, "speaker_id": f"s{int(row['speaker_id'][1:]) % 3}"})
    return path


def test_experiment_rejects_too_few_groups(tmp_path):
    with pytest.raises(ValueError, match="at least 5"):
        run_experiment(
            few_group_features(tmp_path), target="delivery", target_range=(0.0, 5.0), bootstrap=5
        )


def test_experiment_rejects_single_class_training_fold(tmp_path):
    with pytest.raises(ValueError, match="both classes"):
        run_experiment(
            synthetic_features(tmp_path),
            target="delivery",
            target_range=(0.0, 5.0),
            binary_threshold=-1.0,
            bootstrap=5,
        )


def test_experiment_cli_exits_with_message_on_invalid_input(tmp_path):
    from scripts.experiment_delivery import main as experiment_main

    with pytest.raises(SystemExit, match="at least 5"):
        experiment_main(["--features", str(few_group_features(tmp_path)), "--target", "delivery"])
