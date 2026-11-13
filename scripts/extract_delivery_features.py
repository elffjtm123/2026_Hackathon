import argparse
import csv
import math
import re
from collections.abc import Callable, Sequence
from contextlib import ExitStack
from pathlib import Path
from typing import Any

import numpy as np
import soundfile
from scipy.signal import resample_poly

from app.modules.delivery.analyzer import DeliveryAnalyzer
from app.modules.delivery.f0 import F0Extractor, parselmouth_f0
from app.modules.speech.analysis import filler_counts
from app.modules.speech.segments import FRAME_SAMPLES, SAMPLE_RATE, default_is_speech, pcm_rms

REQUIRED = ("utterance_id", "speaker_id", "wav_path", "transcript")
FEATURES = (
    "voiced_ms",
    "syllables",
    "speech_rate",
    "articulation_rate",
    "pause_count",
    "longest_pause_ms",
    "sentence_end_pause_ms",
    "disfluency_density",
    "pvq",
    "loudness_dbfs",
    "f0_median_hz",
    "f0_st",
    "alpha_ratio_db",
    "hammarberg_db",
)
WINDOW_FIELDS = (
    "start_ms",
    "end_ms",
    "voiced_ms",
    "observed_ms",
    "coverage",
    "syllables",
    "disfluencies",
    "speech_rate",
    "articulation_rate",
    "disfluency_density",
    "pause_count",
    "f0_median_hz",
    "f0_st",
    "pvq",
    "loudness_dbfs",
    "loudness_rel_db",
    "alpha_ratio_db",
    "hammarberg_db",
)
SHORT_VOICED_MS = 1000


def load_pcm16(path: Path) -> bytes:
    data, rate = soundfile.read(path, dtype="float32", always_2d=True)
    mono = data.mean(axis=1)
    if rate != SAMPLE_RATE:
        divisor = math.gcd(SAMPLE_RATE, rate)
        mono = resample_poly(mono, SAMPLE_RATE // divisor, rate // divisor)
    return (np.clip(mono, -1, 1) * 32767).astype("<i2").tobytes()


def extract_row(
    pcm: bytes,
    transcript: str,
    is_speech: Callable[[bytes], bool],
    extract_f0: F0Extractor,
) -> tuple[dict[str, object], list[dict[str, Any]]]:
    analyzer = DeliveryAnalyzer(extract_f0)
    step = FRAME_SAMPLES * 2
    for offset in range(0, len(pcm), step):
        frame = pcm[offset : offset + step]
        start = offset // 2 * 1000 // SAMPLE_RATE
        end = (offset + len(frame)) // 2 * 1000 // SAMPLE_RATE
        analyzer.observe_frame(start, end, pcm_rms(frame), is_speech(frame))
    fillers, repeats = filler_counts(transcript)
    analyzer.observe_utterance(
        0,
        len(pcm) // 2 * 1000 // SAMPLE_RATE,
        pcm,
        "flush",
        0,
        len(re.findall(r"[가-힣]", transcript)),
        sum(fillers.values()) + repeats,
    )
    row: dict[str, object] = dict(analyzer.report()["sentences"][0])
    row["short_voiced"] = int(row["voiced_ms"] < SHORT_VOICED_MS)  # type: ignore[operator]
    return row, analyzer.windows()["windows"]


def extract_features(
    manifest: Path,
    out: Path,
    *,
    windows_out: Path | None = None,
    is_speech: Callable[[bytes], bool] | None = None,
    extract_f0: F0Extractor = parselmouth_f0,
) -> None:
    is_speech = is_speech or default_is_speech()
    with manifest.open(encoding="utf-8", newline="") as file:
        reader = csv.DictReader(file)
        labels = [x for x in reader.fieldnames or () if x not in REQUIRED]
        rows = list(reader)
    columns = ["utterance_id", "speaker_id", *labels, *FEATURES, "short_voiced"]
    window_columns = ["utterance_id", "speaker_id", "window_index", *WINDOW_FIELDS]
    with ExitStack() as stack:
        file = stack.enter_context(out.open("w", encoding="utf-8", newline=""))
        writer = csv.DictWriter(file, columns, extrasaction="ignore")
        writer.writeheader()
        window_writer = None
        if windows_out:
            window_file = stack.enter_context(windows_out.open("w", encoding="utf-8", newline=""))
            window_writer = csv.DictWriter(window_file, window_columns)
            window_writer.writeheader()
        for source in rows:
            wav = Path(source["wav_path"])
            wav = wav if wav.is_absolute() else manifest.parent / wav
            row, windows = extract_row(load_pcm16(wav), source["transcript"], is_speech, extract_f0)
            # Sentence-end pause needs a following sentence; each file is one sentence.
            row["sentence_end_pause_ms"] = None
            writer.writerow(
                {
                    **{key: source[key] for key in ("utterance_id", "speaker_id", *labels)},
                    **{key: "" if value is None else value for key, value in row.items()},
                }
            )
            if window_writer:
                for index, window in enumerate(windows):
                    window_writer.writerow(
                        {
                            "utterance_id": source["utterance_id"],
                            "speaker_id": source["speaker_id"],
                            "window_index": index,
                            **{k: "" if window[k] is None else window[k] for k in WINDOW_FIELDS},
                        }
                    )


def parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="발화 단위 전달력 특징을 CSV로 추출합니다.")
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument(
        "--windows-out", type=Path, help="10초 창 단위 특징을 발화 파일별로 따로 저장합니다."
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> None:
    args = parse_args(argv)
    extract_features(args.manifest, args.out, windows_out=args.windows_out)


if __name__ == "__main__":
    main()
