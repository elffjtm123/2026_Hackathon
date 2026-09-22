import argparse
import asyncio
import csv
import json
import time
from pathlib import Path
from typing import Any
from uuid import uuid4

from app.ai.base import MediaPayload
from app.ai.uniface_gaze import UniFaceGazeAdapter
from app.modules.gaze.service import GazeStabilizer

DIRECTIONS = ("center", "left", "right", "up", "down")


def load_labels(path: Path) -> dict[int, str]:
    if path.suffix.lower() == ".json":
        rows = json.loads(path.read_text(encoding="utf-8"))
    else:
        with path.open(encoding="utf-8", newline="") as file:
            rows = list(csv.DictReader(file))
    return {int(row["frame"]): str(row["direction"]).lower() for row in rows}


def f1_score(expected: list[bool], predicted: list[bool]) -> float:
    true_positive = sum(want and got for want, got in zip(expected, predicted, strict=True))
    false_positive = sum(
        not want and got for want, got in zip(expected, predicted, strict=True)
    )
    false_negative = sum(
        want and not got for want, got in zip(expected, predicted, strict=True)
    )
    denominator = 2 * true_positive + false_positive + false_negative
    return 2 * true_positive / denominator if denominator else 0.0


def summarize(records: list[dict[str, Any]]) -> dict[str, Any]:
    labeled = [record for record in records if record["ground_truth"] in DIRECTIONS]
    binary_f1 = f1_score(
        [record["ground_truth"] != "center" for record in labeled],
        [record["prediction"] in DIRECTIONS[1:] for record in labeled],
    )
    per_direction = []
    for direction in DIRECTIONS:
        per_direction.append(
            f1_score(
                [record["ground_truth"] == direction for record in labeled],
                [record["prediction"] == direction for record in labeled],
            )
        )
    latencies = sorted(float(record["latency_ms"]) for record in records)
    p95_index = max(0, round((len(latencies) - 1) * 0.95)) if latencies else 0
    return {
        "binary_f1": round(binary_f1, 4),
        "macro_f1": round(sum(per_direction) / len(per_direction), 4),
        "mean_latency_ms": round(sum(latencies) / len(latencies), 2) if latencies else 0,
        "p95_latency_ms": round(latencies[p95_index], 2) if latencies else 0,
        "no_face_rate": round(
            sum(not record["face_detected"] for record in records) / len(records), 4
        )
        if records
        else 0,
        "sample_count": len(records),
        "l2cs_runtime": {
            "status": "rejected",
            "reason": "공식 실행에 별도 weight 파일이 필요해 localhost 기본 의존성에서 제외",
        },
    }


async def benchmark(provider: str, input_path: Path, labels_path: Path) -> dict[str, Any]:
    import cv2

    if provider == "legacy":
        from app.ai.video_gaze import VideoGazeAdapter

        adapter: Any = VideoGazeAdapter()
    else:
        adapter = UniFaceGazeAdapter()
    labels = load_labels(labels_path)
    stabilizer = GazeStabilizer(calibration_frames=16)
    capture = cv2.VideoCapture(str(input_path))
    fps = capture.get(cv2.CAP_PROP_FPS) or 8.0
    records: list[dict[str, Any]] = []
    frame_index = 0
    try:
        while True:
            ok, frame = capture.read()
            if not ok:
                break
            encoded, jpeg = cv2.imencode(".jpg", frame)
            if not encoded:
                continue
            started = time.perf_counter()
            raw = await adapter.infer(
                MediaPayload(
                    uuid4(),
                    round(frame_index * 1000 / fps),
                    jpeg.tobytes(),
                )
            )
            result = stabilizer.update(raw)
            records.append(
                {
                    "frame": frame_index,
                    "ground_truth": labels.get(frame_index),
                    "prediction": result.metrics["gaze_direction"],
                    "face_detected": result.metrics["face_detected"],
                    "latency_ms": (time.perf_counter() - started) * 1000,
                }
            )
            frame_index += 1
    finally:
        capture.release()
        if hasattr(adapter, "close"):
            adapter.close()
    return {"provider": provider, **summarize(records), "frames": records}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="시선 모델의 방향 분류와 지연을 평가합니다.")
    parser.add_argument("--provider", choices=("uniface", "legacy"), default="uniface")
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--labels", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    result = asyncio.run(benchmark(args.provider, args.input, args.labels))
    args.output.write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps({key: value for key, value in result.items() if key != "frames"}, indent=2))


if __name__ == "__main__":
    main()
