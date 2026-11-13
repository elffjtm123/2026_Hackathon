import argparse
import csv
import json
import math
import re
import subprocess
from collections.abc import Callable, Iterable, Sequence
from pathlib import Path
from typing import Any

import numpy as np
from scipy.stats import spearmanr

from app.modules.speech.analysis import filler_counts

# Ordinal scale for the dataset's letter grades; F is the floor.
GRADE_NUMBERS = {"A+": 8, "A0": 7, "B+": 6, "B0": 5, "C+": 4, "C0": 3, "D+": 2, "D0": 1, "F": 0}
TAGS = ("FIL", "REP", "PS", "WR")
ITEMS = ("repeat", "filler_words", "pause", "wrong", "voc_quality", "voc_speed_sec")
SCORES = tuple(f"{item}_scr" for item in ITEMS)
COUNTS = ("repeat_cnt", "filler_words_cnt", "pause_cnt", "wrong_cnt")
GROUPS = ("expert", "semi-expert", "person")
LABEL_SUFFIX = "_presentation"
NAN = float("nan")


def grade_number(grade: object) -> float:
    return float(GRADE_NUMBERS.get(str(grade).strip(), NAN)) if grade is not None else NAN


def to_float(value: object) -> float:
    """NULL, empty and non-numeric values become NaN."""
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return NAN


def mmss_to_seconds(value: object) -> float:
    match = re.fullmatch(r"\s*(\d+):(\d{1,2})\s*", str(value or ""))
    return float(int(match[1]) * 60 + int(match[2])) if match else NAN


def count_tags(text: object) -> dict[str, int]:
    """Count opening tags like <FIL>어</FIL>. Empty pairs and unclosed tags are tolerated."""
    text = text if isinstance(text, str) else ""
    return {tag: len(re.findall(rf"<{tag}>(?!\s*</{tag}>)", text)) for tag in TAGS}


def clean_transcript(text: object) -> str:
    """14 of 720 STT texts carry stray tag fragments; drop them and squeeze spaces."""
    text = text if isinstance(text, str) else ""
    return " ".join(re.sub(rf"</?(?:{'|'.join(TAGS)})>", " ", text).split())


def section(data: object, key: str) -> dict[str, Any]:
    value = data.get(key) if isinstance(data, dict) else None
    return value if isinstance(value, dict) else {}


def nanmean(values: Iterable[float]) -> float:
    kept = [v for v in values if not math.isnan(v)]
    return float(np.mean(kept)) if kept else NAN


def parse_rater(entry: object) -> dict[str, Any]:
    rater: dict[str, Any] = {
        "flag": section(entry, "evaluation").get("eval_flag"),
        "grade_num": grade_number(section(entry, "evaluation").get("eval_grade")),
    }
    for item in ("repeat", "filler_words", "pause", "wrong"):
        rater[f"{item}_cnt"] = to_float(section(entry, item).get(f"{item}_cnt"))
        rater[f"{item}_scr"] = to_float(section(entry, item).get(f"{item}_scr"))
    rater["voc_quality_scr"] = to_float(section(entry, "voice_quality").get("voc_quality_scr"))
    rater["voc_speed_sec_scr"] = to_float(section(entry, "voice_speed").get("voc_speed_sec_scr"))
    rater["voc_speed"] = to_float(section(entry, "voice_speed").get("voc_speed"))
    return rater


def parse_label(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    script, average = section(data, "script"), section(data, "average")
    evaluations = data.get("evaluations") if isinstance(data, dict) else None
    raters = (
        [parse_rater(x) for x in evaluations if isinstance(x, dict)]
        if isinstance(evaluations, list)
        else []
    )
    start, end = mmss_to_seconds(script.get("start_time")), mmss_to_seconds(script.get("end_time"))
    tags = count_tags(script.get("script_tag_txt"))
    record: dict[str, Any] = {
        "stem": path.stem.removesuffix(LABEL_SUFFIX),
        "age_flag": section(data, "speaker").get("age_flag") or "",
        "gender": section(data, "speaker").get("gender") or "",
        "transcript": clean_transcript(script.get("script_stt_txt")),
        "start_s": start,
        "end_s": end,
        "duration_s": end - start,
        "fil_tag_cnt": tags["FIL"],
        "rep_tag_cnt": tags["REP"],
        "ps_tag_cnt": tags["PS"],
        "label_syllable_cnt": to_float(script.get("syllable_cnt")),
        "grade_num": grade_number(average.get("eval_grade")),
        "raters": raters,
    }
    experts = [r for r in raters if r["flag"] == "expert"]
    for name in SCORES:
        record[f"avg_{name}"] = to_float(average.get(name))
        record[f"expert_{name}"] = nanmean(r[name] for r in experts)
    record["expert_grade_num"] = nanmean(r["grade_num"] for r in experts)
    record["voc_speed_sps"] = nanmean(r["voc_speed"] for r in experts)
    return record


MANIFEST_COLUMNS = (
    "utterance_id",
    "speaker_id",
    "wav_path",
    "transcript",
    *(f"avg_{name}" for name in SCORES),
    "grade_num",
    *(f"expert_{name}" for name in SCORES),
    "expert_grade_num",
    "fil_tag_cnt",
    "rep_tag_cnt",
    "ps_tag_cnt",
    "label_syllable_cnt",
    "voc_speed_sps",
    "duration_s",
    "age_flag",
    "gender",
)


def find_labels(roots: Sequence[Path]) -> list[Path]:
    """Label files from all roots. A stem seen twice keeps the first file."""
    found: dict[str, Path] = {}
    for root in roots:
        for path in sorted(root.rglob(f"*{LABEL_SUFFIX}.json")):
            found.setdefault(path.stem.removesuffix(LABEL_SUFFIX), path)
    return list(found.values())


def find_media(roots: Sequence[Path]) -> dict[str, Path]:
    found: dict[str, Path] = {}
    for root in roots:
        for path in sorted(root.rglob("*.mp4")):
            found.setdefault(path.stem, path)
    return found


def extract_audio(
    media: Path, wav: Path, start_s: float, duration_s: float, run: Callable[..., Any]
) -> None:
    """16 kHz mono PCM16 wav, cropped when the label has a valid time range."""
    crop: list[str] = []
    if not (math.isnan(duration_s) or duration_s <= 0):
        crop = ["-ss", f"{start_s:g}", "-i", str(media), "-t", f"{duration_s:g}"]
    part = wav.with_name(wav.name + ".part")
    command = [
        "ffmpeg", "-y", "-loglevel", "error",
        *(crop or ["-i", str(media)]),
        "-vn", "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", "-f", "wav", str(part),
    ]  # fmt: skip
    try:
        run(command, check=True, capture_output=True)
        part.replace(wav)
    finally:
        part.unlink(missing_ok=True)


def build_manifest(
    label_roots: Sequence[Path],
    media_roots: Sequence[Path],
    out_dir: Path,
    run: Callable[..., Any] = subprocess.run,
) -> dict[str, Any]:
    media = find_media(media_roots)
    labels = find_labels(label_roots)
    wav_dir = out_dir / "wav16k"
    wav_dir.mkdir(parents=True, exist_ok=True)
    rows: list[dict[str, Any]] = []
    unmatched = 0
    failures: list[str] = []
    stems = set()
    for path in labels:
        record = parse_label(path)
        stems.add(record["stem"])
        source = media.get(record["stem"])
        if source is None:
            unmatched += 1
            continue
        wav = wav_dir / f"{record['stem']}.wav"
        if not wav.exists():
            try:
                extract_audio(source, wav, record["start_s"], record["duration_s"], run)
            except (subprocess.CalledProcessError, OSError):
                failures.append(record["stem"])
                continue
        rows.append(
            {
                **record,
                "utterance_id": record["stem"],
                "speaker_id": record["stem"],
                "wav_path": f"wav16k/{record['stem']}.wav",
            }
        )
    with (out_dir / "manifest.csv").open("w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, MANIFEST_COLUMNS, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow(
                {k: "" if isinstance(v, float) and math.isnan(v) else v for k, v in row.items()}
            )
    return {
        "rows": len(rows),
        "labels_without_media": unmatched,
        "media_without_label": len(set(media) - stems),
        "ffmpeg_failures": failures,
    }


def spearman(x: Iterable[float], y: Iterable[float]) -> float | None:
    """Spearman over pairs where both values exist; None when undefined."""
    pairs = [(a, b) for a, b in zip(x, y, strict=True) if not (math.isnan(a) or math.isnan(b))]
    if len(pairs) < 3:
        return None
    a, b = zip(*pairs, strict=True)
    if len(set(a)) < 2 or len(set(b)) < 2:
        return None
    return float(spearmanr(a, b)[0])


def icc2k(matrix: Sequence[Sequence[float]]) -> float | None:
    """ICC(2,k): two-way random effects, average of k raters (Shrout & Fleiss 1979)."""
    data = np.asarray(matrix, dtype=float)
    if data.ndim != 2 or data.shape[0] < 2 or data.shape[1] < 2:
        return None
    n, k = data.shape
    grand = data.mean()
    rows, cols = data.mean(axis=1), data.mean(axis=0)
    msr = k * ((rows - grand) ** 2).sum() / (n - 1)
    msc = n * ((cols - grand) ** 2).sum() / (k - 1)
    sse = ((data - rows[:, None] - cols[None, :] + grand) ** 2).sum()
    mse = sse / ((n - 1) * (k - 1))
    denominator = msr + (msc - mse) / n
    return None if denominator <= 1e-12 else float((msr - mse) / denominator)


def finite(values: Iterable[float]) -> list[float]:
    return [v for v in values if not math.isnan(v)]


def distribution(values: Sequence[float], *, bucket: bool) -> dict[str, Any]:
    kept = finite(values)
    if not kept:
        return {"n": 0, "mean": None, "sd": None, "min": None, "max": None, "counts": {}}
    counts: dict[str, int] = {}
    for v in sorted(kept):
        key = f"{math.floor(v + 0.5) if bucket else v:g}"
        counts[key] = counts.get(key, 0) + 1
    return {
        "n": len(kept),
        "mean": float(np.mean(kept)),
        "sd": float(np.std(kept, ddof=1)) if len(kept) > 1 else None,
        "min": min(kept),
        "max": max(kept),
        "counts": counts,
    }


def agreement(records: Sequence[dict[str, Any]], item: str, group: str) -> dict[str, Any] | None:
    """Files x raters matrix for one rater group. Raters sit at fixed list positions."""
    width = max((len(r["raters"]) for r in records), default=0)
    columns = [
        [
            r["raters"][i][item]
            if i < len(r["raters"]) and r["raters"][i]["flag"] == group
            else NAN
            for r in records
        ]
        for i in range(width)
    ]
    columns = [c for c in columns if finite(c)]
    if len(columns) < 2:
        return None
    matrix = np.array(columns, dtype=float).T
    complete = matrix[~np.isnan(matrix).any(axis=1)]
    pairwise = [
        rho
        for i in range(len(columns))
        for j in range(i + 1, len(columns))
        if (rho := spearman(matrix[:, i], matrix[:, j])) is not None
    ]
    return {
        "n_files": int(len(complete)),
        "n_raters": len(columns),
        "icc2k": icc2k(complete),
        "mean_pairwise_spearman": float(np.mean(pairwise)) if pairwise else None,
        "all_identical_share": float((complete == complete[:, :1]).all(axis=1).mean())
        if len(complete)
        else None,
    }


def stt_comparison(
    stt: Sequence[float], tags: Sequence[float], names: tuple[str, str]
) -> dict[str, Any]:
    stt_total, tag_total = float(sum(stt)), float(sum(tags))
    return {
        "stt": names[0],
        "tags": names[1],
        "n": len(stt),
        "spearman": spearman(stt, tags),
        "stt_total": int(stt_total),
        "tag_total": int(tag_total),
        "ratio": stt_total / tag_total if tag_total else None,
    }


def labels_report(records: Sequence[dict[str, Any]]) -> dict[str, Any]:
    def column(name: str) -> list[float]:
        return [float(r[name]) for r in records]

    scores = [f"avg_{name}" for name in SCORES]
    report: dict[str, Any] = {"n_files": len(records)}
    report["distributions"] = {
        **{name: distribution(column(name), bucket=True) for name in scores},
        "grade_num": distribution(column("grade_num"), bucket=False),
    }
    report["agreement"] = {}
    for item in (*SCORES, "grade_num"):
        found = {g: a for g in GROUPS if (a := agreement(records, item, g)) is not None}
        report["agreement"][item] = found

    mean_counts = {
        name: [nanmean(x[name] for x in r["raters"]) for r in records] for name in COUNTS
    }
    report["score_vs_counts"] = []
    for item, tag in (
        ("repeat", "rep_tag_cnt"),
        ("filler_words", "fil_tag_cnt"),
        ("pause", "ps_tag_cnt"),
    ):
        score = column(f"avg_{item}_scr")
        for count_name, counts in (
            (f"mean_{item}_cnt", mean_counts[f"{item}_cnt"]),
            (tag, column(tag)),
        ):
            report["score_vs_counts"].append(
                {
                    "score": f"avg_{item}_scr",
                    "count": count_name,
                    "n": len(finite(a + b for a, b in zip(score, counts, strict=True))),
                    "spearman": spearman(score, counts),
                }
            )

    rater_pairs = [
        (r["voc_speed"], r["voc_speed_sec_scr"])
        for rec in records
        for r in rec["raters"]
        if not (math.isnan(r["voc_speed"]) or math.isnan(r["voc_speed_sec_scr"]))
    ]
    by_score: dict[int, list[float]] = {}
    for sps, score in rater_pairs:
        by_score.setdefault(int(math.floor(score + 0.5)), []).append(sps)
    report["speed"] = {
        "spearman": spearman(column("avg_voc_speed_sec_scr"), column("voc_speed_sps")),
        "table": [
            {
                "score": score,
                "n": len(values),
                "min": min(values),
                "p05": float(np.percentile(values, 5)),
                "median": float(np.median(values)),
                "p95": float(np.percentile(values, 95)),
                "max": max(values),
            }
            for score, values in sorted(by_score.items())
        ],
    }

    fillers, repeats = [], []
    for r in records:
        found, repeated = filler_counts(r["transcript"])
        fillers.append(sum(found.values()))
        repeats.append(repeated)
    fil, rep = column("fil_tag_cnt"), column("rep_tag_cnt")
    report["stt_check"] = {
        "combined": stt_comparison(
            [a + b for a, b in zip(fillers, repeats, strict=True)],
            [a + b for a, b in zip(fil, rep, strict=True)],
            ("fillers+repeats", "FIL+REP tags"),
        ),
        "fillers_vs_fil": stt_comparison(fillers, fil, ("fillers", "FIL tags")),
        "repeats_vs_rep": stt_comparison(repeats, rep, ("repeats", "REP tags")),
    }
    report["grade_vs_items"] = {
        name: spearman(column("grade_num"), column(name)) for name in scores
    }
    return report


def fmt(value: float | None, digits: int = 3) -> str:
    return "-" if value is None else f"{value:.{digits}f}"


def render(report: dict[str, Any]) -> str:
    lines = [f"files={report['n_files']}"]
    if not report["n_files"]:
        return lines[0]
    lines.append(
        "\n== score distributions (counts bucketed to the nearest integer; grade exact) =="
    )
    for name, d in report["distributions"].items():
        counts = " ".join(f"{k}:{v}" for k, v in d["counts"].items())
        lines.append(
            f"{name.ljust(26)}n={d['n']} mean={fmt(d['mean'])} sd={fmt(d['sd'])} "
            f"min={fmt(d['min'], 2)} max={fmt(d['max'], 2)}  {counts}"
        )
    lines.append(
        "\n== rater agreement (ICC(2,k), mean pairwise Spearman, share of identical files) =="
    )
    for item, groups in report["agreement"].items():
        for group, a in groups.items():
            lines.append(
                f"{item.ljust(20)}{group.ljust(13)}files={a['n_files']} raters={a['n_raters']} "
                f"ICC={fmt(a['icc2k'])} rho={fmt(a['mean_pairwise_spearman'])} "
                f"identical={fmt(a['all_identical_share'], 2)}"
            )
    lines.append("\n== score vs counts (Spearman) ==")
    for p in report["score_vs_counts"]:
        lines.append(
            f"{p['score'].ljust(26)}{p['count'].ljust(24)}rho={fmt(p['spearman'])} n={p['n']}"
        )
    speed = report["speed"]
    lines.append(f"\n== voc_speed_sec_scr vs SPS: file-level Spearman={fmt(speed['spearman'])} ==")
    lines.append(
        "score      n    min   p05   median  p95   max   (rater-level SPS per integer score)"
    )
    for r in speed["table"]:
        lines.append(
            f"{str(r['score']).ljust(7)}{str(r['n']).rjust(6)}  {fmt(r['min'], 2)}  "
            f"{fmt(r['p05'], 2)}  {fmt(r['median'], 2)}   {fmt(r['p95'], 2)}  {fmt(r['max'], 2)}"
        )
    lines.append("\n== STT filler detection vs tags (per file) ==")
    for c in report["stt_check"].values():
        lines.append(
            f"{c['stt']} vs {c['tags']}: rho={fmt(c['spearman'])} stt_total={c['stt_total']} "
            f"tag_total={c['tag_total']} ratio={fmt(c['ratio'])} n={c['n']}"
        )
    lines.append("\n== grade_num vs item score (Spearman) ==")
    for name, rho in report["grade_vs_items"].items():
        lines.append(f"{name.ljust(26)}{fmt(rho)}")
    return "\n".join(lines)


def parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="AI Hub 71663 공적말하기(언어적) 라벨 점검과 매니페스트 생성. "
        "화자 ID가 없으므로 파일 stem을 그룹 ID로 쓴다(화자 정체는 알 수 없음).",
        epilog="grade map (ordinal): " + " ".join(f"{k}={v}" for k, v in GRADE_NUMBERS.items()),
    )
    commands = parser.add_subparsers(dest="command", required=True)
    manifest = commands.add_parser(
        "manifest", help="mp4에서 16kHz wav를 추출하고 manifest.csv를 씁니다."
    )
    manifest.add_argument("--labels", type=Path, nargs="+", required=True)
    manifest.add_argument("--media", type=Path, nargs="+", required=True)
    manifest.add_argument("--out-dir", type=Path, required=True)
    report = commands.add_parser(
        "labels-report", help="라벨만으로 점수 분포와 평가자 일치도를 봅니다."
    )
    report.add_argument("--labels", type=Path, nargs="+", required=True)
    report.add_argument("--out-json", type=Path)
    return parser.parse_args(argv)


def json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): json_safe(v) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return [json_safe(v) for v in value]
    if isinstance(value, float) and math.isnan(value):
        return None
    return value


def main(argv: Sequence[str] | None = None) -> None:
    args = parse_args(argv)
    if args.command == "manifest":
        summary = build_manifest(args.labels, args.media, args.out_dir)
        print(
            f"manifest rows={summary['rows']} "
            f"labels_without_media={summary['labels_without_media']} "
            f"media_without_label={summary['media_without_label']} "
            f"ffmpeg_failures={len(summary['ffmpeg_failures'])}"
        )
        for stem in summary["ffmpeg_failures"]:
            print(f"  ffmpeg failed: {stem}")
        return
    report = labels_report([parse_label(path) for path in find_labels(args.labels)])
    print(render(report))
    if args.out_json:
        args.out_json.write_text(
            json.dumps(json_safe(report), ensure_ascii=False, indent=2), encoding="utf-8"
        )


if __name__ == "__main__":
    main()
