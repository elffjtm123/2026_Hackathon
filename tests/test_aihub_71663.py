import csv
import json
import math
import shutil
import subprocess
from pathlib import Path

import pytest
import soundfile

from scripts.aihub_71663 import (
    GRADE_NUMBERS,
    build_manifest,
    count_tags,
    grade_number,
    icc2k,
    labels_report,
    main,
    mmss_to_seconds,
    parse_label,
    render,
    spearman,
)


def rater(flag, grade, scores, speed=None, counts=(0, 0, 0, 0)):
    names = ("repeat", "filler_words", "pause", "wrong")
    entry: dict = {"evaluation": {"eval_id": "P", "eval_flag": flag, "eval_grade": grade}}
    for name, count, score in zip(names, counts, scores[:4], strict=True):
        entry[name] = {f"{name}_cnt": count, f"{name}_scr": score}
    entry["voice_quality"] = {"voc_quality": "VCQ03", "voc_quality_scr": scores[4]}
    entry["voice_speed"] = {"voc_speed": speed, "voc_speed_sec_scr": scores[5]}
    return entry


def label(raters, *, tag="", stt="안녕 하세요", start="00:10", end="01:10", average=None):
    return {
        "speaker": {"age_flag": "A02", "gender": "여자"},
        "script": {
            "start_time": start,
            "end_time": end,
            "script_stt_txt": stt,
            "script_tag_txt": tag,
            "syllable_cnt": 5,
        },
        "evaluations": raters,
        "average": average
        or {
            "repeat_scr": 4.0,
            "filler_words_scr": 3.0,
            "pause_scr": 5.0,
            "wrong_scr": 4.5,
            "voc_quality_scr": 3.5,
            "voc_speed_sec_scr": 2.0,
            "eval_grade": "B+",
        },
    }


def write_label(directory: Path, stem: str, data: dict) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{stem}_presentation.json"
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return path


def test_grade_map_is_ordinal_and_tolerates_junk():
    assert [GRADE_NUMBERS[g] for g in ("A+", "A0", "B+", "B0", "C+", "C0", "D+", "D0", "F")] == [
        8,
        7,
        6,
        5,
        4,
        3,
        2,
        1,
        0,
    ]
    assert grade_number("C+") == 4
    assert math.isnan(grade_number(None))
    assert math.isnan(grade_number(""))
    assert math.isnan(grade_number("Z"))


def test_count_tags_counts_opening_tags_and_skips_empty_ones():
    text = "음 <FIL>어</FIL> 그 <REP>가 가</REP> <FIL> 음 </FIL> <WR></WR> <PS>x</PS> <FIL>미완"
    assert count_tags(text) == {"FIL": 3, "REP": 1, "PS": 1, "WR": 0}
    assert count_tags(None) == {"FIL": 0, "REP": 0, "PS": 0, "WR": 0}


def test_mmss_to_seconds():
    assert mmss_to_seconds("03:24") == 204
    assert math.isnan(mmss_to_seconds(""))
    assert math.isnan(mmss_to_seconds(None))
    assert math.isnan(mmss_to_seconds("abc"))


def test_parse_label_handles_null_and_missing_sections(tmp_path):
    raters = [
        rater("expert", "B0", (5, 4, 3, 2, 4, 3), speed=4.0, counts=(1, 2, 0, 1)),
        rater("expert", "C+", (3, 2, 1, 4, 2, 5), speed=5.0, counts=(1, 2, 0, 1)),
        rater("person", "F", (None, None, None, None, None, None), counts=(3, 2, 0, 1)),
    ]
    raters[2]["voice_quality"]["voc_quality_scr"] = ""
    del raters[2]["wrong"]
    data = label(raters, tag="<FIL>어</FIL> <REP>a a</REP>")
    record = parse_label(write_label(tmp_path, "A02_S01_F_X_01_001_02_WA_MO", data))
    assert record["stem"] == "A02_S01_F_X_01_001_02_WA_MO"
    assert (record["age_flag"], record["gender"]) == ("A02", "여자")
    assert record["duration_s"] == 60
    assert (record["fil_tag_cnt"], record["rep_tag_cnt"]) == (1, 1)
    assert record["avg_filler_words_scr"] == 3.0
    assert record["grade_num"] == 6
    assert record["expert_repeat_scr"] == 4.0
    assert record["expert_grade_num"] == 4.5
    assert record["voc_speed_sps"] == 4.5
    person = record["raters"][2]
    assert person["flag"] == "person" and person["grade_num"] == 0
    assert math.isnan(person["repeat_scr"]) and math.isnan(person["wrong_cnt"])
    assert person["filler_words_cnt"] == 2


def test_parse_label_with_no_sections_gives_nan_not_crash(tmp_path):
    record = parse_label(write_label(tmp_path, "empty", {}))
    assert record["raters"] == []
    assert math.isnan(record["avg_pause_scr"]) and math.isnan(record["grade_num"])
    assert math.isnan(record["voc_speed_sps"]) and math.isnan(record["duration_s"])
    assert record["transcript"] == ""


STEM = "A02_S01_F_X_01_001_02_WA_MO"


def simple_label() -> dict:
    return label(
        [rater("expert", "B0", (5, 4, 3, 2, 4, 3), speed=4.0)],
        tag="<FIL>어</FIL> <REP>a a</REP> <REP>b b</REP>",
    )


def fake_ffmpeg(calls: list):
    def run(command, **kwargs):
        calls.append(command)
        assert isinstance(command, list) and not kwargs.get("shell")
        Path(command[-1]).write_bytes(b"RIFF")

    return run


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as file:
        return list(csv.DictReader(file))


def test_manifest_matches_stems_crops_audio_and_reports_orphans(tmp_path):
    labels, media, out = tmp_path / "labels", tmp_path / "media", tmp_path / "out"
    write_label(labels, STEM, simple_label())
    write_label(labels, "nomedia", simple_label())
    (media / "nested").mkdir(parents=True)
    (media / "nested" / f"{STEM}.mp4").write_bytes(b"x")
    (media / "orphan.mp4").write_bytes(b"x")
    calls: list = []
    summary = build_manifest([labels], [media], out, run=fake_ffmpeg(calls))
    assert summary["rows"] == 1
    assert summary["labels_without_media"] == 1
    assert summary["media_without_label"] == 1
    (command,) = calls
    assert command[0] == "ffmpeg"
    assert command[command.index("-ss") + 1] == "10" and command[command.index("-t") + 1] == "60"
    assert command[command.index("-ar") + 1] == "16000" and command[command.index("-ac") + 1] == "1"
    assert "pcm_s16le" in command
    assert (out / "wav16k" / f"{STEM}.wav").exists()
    assert not list((out / "wav16k").glob("*.part"))
    (row,) = read_csv(out / "manifest.csv")
    assert (row["utterance_id"], row["speaker_id"], row["wav_path"]) == (
        STEM,
        STEM,
        f"wav16k/{STEM}.wav",
    )
    assert row["transcript"] == "안녕 하세요"
    assert (row["fil_tag_cnt"], row["rep_tag_cnt"], row["grade_num"]) == ("1", "2", "6.0")
    assert row["avg_filler_words_scr"] == "3.0" and row["expert_repeat_scr"] == "5.0"
    assert row["voc_speed_sps"] == "4.0" and row["duration_s"] == "60.0"
    assert (row["age_flag"], row["gender"], row["label_syllable_cnt"]) == ("A02", "여자", "5.0")


def test_manifest_skips_existing_wav_and_blank_for_nan(tmp_path):
    labels, media, out = tmp_path / "labels", tmp_path / "media", tmp_path / "out"
    write_label(labels, STEM, label([], start="", end=""))
    media.mkdir()
    (media / f"{STEM}.mp4").write_bytes(b"x")
    (out / "wav16k").mkdir(parents=True)
    (out / "wav16k" / f"{STEM}.wav").write_bytes(b"old")
    calls: list = []
    build_manifest([labels], [media], out, run=fake_ffmpeg(calls))
    assert calls == []
    (row,) = read_csv(out / "manifest.csv")
    assert row["duration_s"] == "" and row["voc_speed_sps"] == ""


def test_manifest_without_times_converts_whole_file_and_survives_ffmpeg_failure(tmp_path):
    labels, media, out = tmp_path / "labels", tmp_path / "media", tmp_path / "out"
    write_label(labels, STEM, label([], start="", end=""))
    write_label(labels, "bad", label([]))
    media.mkdir()
    for stem in (STEM, "bad"):
        (media / f"{stem}.mp4").write_bytes(b"x")
    calls: list = []

    def run(command, **kwargs):
        if "bad.mp4" in " ".join(command):
            raise subprocess.CalledProcessError(1, command)
        fake_ffmpeg(calls)(command, **kwargs)

    summary = build_manifest([labels], [media], out, run=run)
    assert "-ss" not in calls[0] and "-t" not in calls[0]
    assert summary["rows"] == 1 and summary["ffmpeg_failures"] == ["bad"]
    assert not (out / "wav16k" / "bad.wav.part").exists()


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg not installed")
def test_manifest_real_ffmpeg_makes_16k_mono_pcm16_cropped_wav(tmp_path):
    labels, media, out = tmp_path / "labels", tmp_path / "media", tmp_path / "out"
    media.mkdir()
    subprocess.run(
        [
            "ffmpeg",
            "-loglevel",
            "error",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=300:duration=4",
            "-ac",
            "2",
            "-ar",
            "44100",
            "-c:a",
            "aac",
            str(media / f"{STEM}.mp4"),
        ],
        check=True,
    )
    write_label(labels, STEM, label([], start="00:01", end="00:03"))
    build_manifest([labels], [media], out)
    info = soundfile.info(out / "wav16k" / f"{STEM}.wav")
    assert (info.samplerate, info.channels, info.subtype) == (16_000, 1, "PCM_16")
    assert abs(info.duration - 2.0) < 0.1


REPORT_STEMS = ["f0", "f1", "f2", "f3"]
STT = ["안녕하세요", "음 안녕", "음 어 안녕 안녕 안녕", "안녕 안녕"]
TAGS = ["", "<FIL>음</FIL>", "<FIL>a</FIL><FIL>b</FIL><FIL>c</FIL><REP>d d</REP>",
        "<FIL>a</FIL><FIL>b</FIL><REP>d d</REP>"]  # fmt: skip
GRADES = ["C0", "C+", "B0", "B+"]


def report_records(tmp_path: Path) -> list[dict]:
    for i, stem in enumerate(REPORT_STEMS):
        speed, counts = 4 + 0.5 * i, (0, i, 0, 0)
        nothing = (None,) * 6
        raters = [
            rater("expert", GRADES[i], (i + 1, 4, 3, 3, 3, i + 1), speed=speed, counts=counts),
            rater("expert", GRADES[i], (i + 2, 4, 3, 3, 3, i + 1), speed=speed, counts=counts),
            rater("person", "F", nothing, counts=counts),
            rater("person", "F", nothing, counts=counts),
        ]
        average = {
            "repeat_scr": i + 1.5,
            "filler_words_scr": 5 - i,
            "pause_scr": 3,
            "wrong_scr": 3,
            "voc_quality_scr": 3,
            "voc_speed_sec_scr": i + 1,
            "eval_grade": GRADES[i],
        }
        write_label(tmp_path, stem, label(raters, tag=TAGS[i], stt=STT[i], average=average))
    return [parse_label(tmp_path / f"{stem}_presentation.json") for stem in REPORT_STEMS]


def test_icc2k_matches_hand_computation():
    # n=4 targets, k=2 raters: MSR=10/3, MSC=2, MSE=0 -> (10/3) / (10/3 + 2/4) = 20/23
    assert icc2k([[1, 2], [2, 3], [3, 4], [4, 5]]) == pytest.approx(20 / 23)
    assert icc2k([[4, 4], [4, 4], [4, 4]]) is None
    assert icc2k([[1, 2]]) is None


def test_spearman_ignores_nan_and_constants():
    assert spearman([1, 2, math.nan, 4], [2, 4, 1, 8]) == pytest.approx(1.0)
    assert spearman([1, 1, 1], [1, 2, 3]) is None
    assert spearman([1, 2], [1, 2]) is None


def test_labels_report_numbers(tmp_path):
    report = labels_report(report_records(tmp_path))
    assert report["n_files"] == 4
    dist = report["distributions"]["avg_repeat_scr"]
    assert (dist["n"], dist["mean"], dist["min"], dist["max"]) == (4, 3.0, 1.5, 4.5)
    assert dist["sd"] == pytest.approx(math.sqrt(5 / 3))
    assert report["distributions"]["avg_voc_speed_sec_scr"]["counts"] == {
        "1": 1, "2": 1, "3": 1, "4": 1
    }  # fmt: skip
    assert report["distributions"]["grade_num"]["mean"] == 4.5

    repeat = report["agreement"]["repeat_scr"]["expert"]
    assert repeat["n_files"] == 4 and repeat["n_raters"] == 2
    assert repeat["icc2k"] == pytest.approx(20 / 23)
    assert repeat["mean_pairwise_spearman"] == pytest.approx(1.0)
    assert repeat["all_identical_share"] == 0.0
    filler = report["agreement"]["filler_words_scr"]["expert"]
    assert filler["icc2k"] is None and filler["all_identical_share"] == 1.0
    assert "person" not in report["agreement"]["repeat_scr"]
    assert report["agreement"]["grade_num"]["person"]["all_identical_share"] == 1.0

    pairs = {(p["score"], p["count"]): p["spearman"] for p in report["score_vs_counts"]}
    assert pairs[("avg_filler_words_scr", "mean_filler_words_cnt")] == pytest.approx(-1.0)
    assert pairs[("avg_filler_words_scr", "fil_tag_cnt")] == pytest.approx(-0.8)
    assert pairs[("avg_repeat_scr", "rep_tag_cnt")] == pytest.approx(4 / math.sqrt(20))
    assert pairs[("avg_pause_scr", "ps_tag_cnt")] is None

    speed = report["speed"]
    assert speed["spearman"] == pytest.approx(1.0)
    row = next(r for r in speed["table"] if r["score"] == 1)
    assert (row["n"], row["min"], row["median"], row["max"]) == (2, 4.0, 4.0, 4.0)

    stt = report["stt_check"]["combined"]
    assert (stt["stt_total"], stt["tag_total"], stt["ratio"]) == (6, 8, 0.75)
    assert stt["spearman"] == pytest.approx(math.sqrt(0.9))
    assert report["stt_check"]["fillers_vs_fil"]["stt_total"] == 3
    assert report["stt_check"]["fillers_vs_fil"]["tag_total"] == 6

    grade = report["grade_vs_items"]
    assert grade["avg_repeat_scr"] == pytest.approx(1.0)
    assert grade["avg_filler_words_scr"] == pytest.approx(-1.0)
    assert grade["avg_pause_scr"] is None


def test_render_and_cli_write_json(tmp_path, capsys):
    report_records(tmp_path / "labels")
    out = tmp_path / "report.json"
    main(["labels-report", "--labels", str(tmp_path / "labels"), "--out-json", str(out)])
    text = capsys.readouterr().out
    assert "ICC" in text and "avg_repeat_scr" in text
    data = json.loads(out.read_text(encoding="utf-8"))
    assert data["n_files"] == 4 and data["agreement"]["filler_words_scr"]["expert"]["icc2k"] is None
    assert render(labels_report([])).startswith("files=0")


def test_parse_label_strips_stray_tags_from_stt_transcript(tmp_path):
    data = label([], stt="<FIL>어 안녕 <REP>하세요</WR> 네")
    record = parse_label(write_label(tmp_path, "stray", data))
    assert record["transcript"] == "어 안녕 하세요 네"
