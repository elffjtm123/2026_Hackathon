import gc
import math
import weakref

import numpy as np
import pytest

from app.modules.delivery.analyzer import DeliveryAnalyzer
from app.modules.delivery.features import (
    articulation_rate,
    disfluency_density,
    find_bursts,
    median_dbfs,
    pvq,
)


def fake_f0(values=()):
    return lambda pcm: [(i * 20, v) for i, v in enumerate(values)]


def tone(ms, freq=300.0):
    t = np.arange(ms * 16) / 16_000
    return (0.3 * 32767 * np.sin(2 * math.pi * freq * t)).astype("<i2").tobytes()


def feed(analyzer, start, end, voiced=True, rms=0.1):
    for t in range(start, end, 20):
        analyzer.observe_frame(t, t + 20, rms, voiced)


def utter(analyzer, start, end, sentence=0, syllables=0, disfluencies=0, cut="endpoint"):
    analyzer.observe_utterance(start, end, b"\0\0", cut, sentence, syllables, disfluencies)


def sentence(analyzer, index=0):
    return next(x for x in analyzer.report()["sentences"] if x["sentence_index"] == index)


def test_pure_feature_math():
    assert articulation_rate(10, 2000) == 300
    assert articulation_rate(10, 0) is None
    assert disfluency_density(3, 6000) == 30
    assert disfluency_density(3, 0) is None
    assert median_dbfs([0.1, 0.1, 0.01]) == pytest.approx(-20)
    assert median_dbfs([]) is None
    assert pvq([100.0, 200.0]) == pytest.approx(1 / 3)
    assert pvq([]) is None
    assert pvq([150.0]) is None


def test_voiced_time_syllables_rate_and_density():
    a = DeliveryAnalyzer(fake_f0())
    feed(a, 0, 6000)
    utter(a, 0, 6000, syllables=30, disfluencies=3)
    s = sentence(a)
    assert (s["voiced_ms"], s["syllables"]) == (6000, 30)
    assert s["articulation_rate"] == 300
    assert s["disfluency_density"] == 30


def test_in_sentence_pause_comes_from_frames_and_short_gaps_are_ignored():
    a = DeliveryAnalyzer(fake_f0())
    feed(a, 0, 2000)
    feed(a, 2000, 2600, voiced=False, rms=0.0)
    utter(a, 0, 2100)
    feed(a, 2600, 4000)
    feed(a, 4000, 4200, voiced=False, rms=0.0)
    feed(a, 4200, 5000)
    utter(a, 2400, 5000)
    s = sentence(a)
    assert (s["pause_count"], s["longest_pause_ms"]) == (1, 600)


def test_max_length_cut_does_not_create_a_pause():
    a = DeliveryAnalyzer(fake_f0())
    feed(a, 0, 8000)
    utter(a, 0, 8000, cut="max_length")
    feed(a, 8000, 9000)
    utter(a, 8000, 9000, cut="flush")
    s = sentence(a)
    assert (s["pause_count"], s["longest_pause_ms"]) == (0, 0)
    assert s["voiced_ms"] == 9000


def test_sentence_end_pause_spans_the_gap_and_last_sentence_is_null():
    a = DeliveryAnalyzer(fake_f0())
    feed(a, 0, 2000)
    utter(a, 0, 2100, sentence=0)
    feed(a, 2800, 4000)
    utter(a, 2600, 4000, sentence=1)
    assert sentence(a, 0)["sentence_end_pause_ms"] == 800
    assert sentence(a, 0)["pause_count"] == 0
    assert sentence(a, 1)["sentence_end_pause_ms"] is None


def test_gap_between_utterances_of_one_sentence_is_an_in_sentence_pause():
    a = DeliveryAnalyzer(fake_f0())
    feed(a, 0, 1000)
    utter(a, 0, 1100, sentence=0)
    feed(a, 2000, 3000)
    utter(a, 1900, 3000, sentence=0)
    s = sentence(a)
    assert (s["pause_count"], s["longest_pause_ms"]) == (1, 1000)
    assert s["sentence_end_pause_ms"] is None


def test_pvq_is_pooled_across_utterances_of_a_sentence():
    values = iter([[(0, 100.0)], [(0, 200.0)]])
    a = DeliveryAnalyzer(lambda pcm: next(values))
    feed(a, 0, 1000)
    utter(a, 0, 1000)
    feed(a, 2000, 3000)
    utter(a, 2000, 3000)
    assert sentence(a)["pvq"] == pytest.approx(1 / 3)


def test_loudness_is_median_dbfs_over_voiced_frames_only():
    a = DeliveryAnalyzer(fake_f0())
    feed(a, 0, 40, rms=0.1)
    feed(a, 40, 60, rms=0.01)
    feed(a, 60, 1000, voiced=False, rms=0.5)
    utter(a, 0, 1000)
    assert sentence(a)["loudness_dbfs"] == pytest.approx(-20)


def test_burst_needs_three_disfluencies_in_ten_voiced_seconds():
    a = DeliveryAnalyzer(fake_f0())
    for index in range(3):
        start = index * 2000
        feed(a, start, start + 2000)
        utter(a, start, start + 2000, sentence=4, disfluencies=1)
    assert a.report()["bursts"] == [{"time_ms": 4000, "sentence_index": 4, "count": 3}]


def test_spread_out_disfluencies_make_no_burst():
    a = DeliveryAnalyzer(fake_f0())
    for index in range(3):
        start = index * 8000
        feed(a, start, start + 8000)
        utter(a, start, start + 8000, disfluencies=1)
    assert a.report()["bursts"] == []


def test_find_bursts_resets_after_an_event():
    items = [(0, 2, 0, 1), (1000, 2, 1000, 1), (2000, 2, 2000, 1)]
    assert find_bursts(items) == [{"time_ms": 1000, "sentence_index": 1, "count": 4}]


def test_status_is_unavailable_under_60s_voiced():
    a = DeliveryAnalyzer(fake_f0())
    feed(a, 0, 59_000)
    utter(a, 0, 59_000)
    assert a.report()["status"] == "unavailable"
    feed(a, 59_000, 60_000)
    utter(a, 59_000, 60_000)
    assert a.report()["status"] == "observed"


def test_baseline_uses_only_sentences_with_3s_voiced():
    a = DeliveryAnalyzer(fake_f0())
    for index, (length, syllables) in enumerate([(3000, 15), (4000, 40), (5000, 100), (1000, 999)]):
        start = index * 10_000
        feed(a, start, start + length)
        utter(a, start, start + length, sentence=index, syllables=syllables)
    baseline = a.report()["baseline"]
    assert baseline["articulation_rate"] == pytest.approx(600)
    assert baseline["voiced_ms"] == 4000


def test_raw_pcm_is_not_retained():
    class Pcm(bytearray):
        pass

    a = DeliveryAnalyzer(fake_f0([100.0, 120.0]))
    feed(a, 0, 1000)
    pcm = Pcm(tone(1000))
    ref = weakref.ref(pcm)
    a.observe_utterance(0, 1000, pcm, "endpoint", 0, 3, 0)  # type: ignore[arg-type]
    del pcm
    gc.collect()
    assert ref() is None
    assert sentence(a)["pvq"] is not None
    assert sentence(a)["alpha_ratio_db"] is not None


def test_out_of_order_utterances_are_rejected():
    a = DeliveryAnalyzer(extract_f0=fake_f0())
    utter(a, 1000, 2000, sentence=1)
    with pytest.raises(ValueError, match="sentence_index"):
        utter(a, 2000, 3000, sentence=0)
    with pytest.raises(ValueError, match="start_ms"):
        utter(a, 500, 900, sentence=1)
    utter(a, 1000, 1500, sentence=1)


def test_speech_rate_spans_first_to_last_voiced_frame_pauses_included():
    a = DeliveryAnalyzer(fake_f0())
    feed(a, 0, 2000)
    feed(a, 2000, 4000, voiced=False, rms=0.0)
    feed(a, 4000, 6000)
    utter(a, 0, 6000, syllables=20)
    s = sentence(a)
    assert s["speech_rate"] == pytest.approx(200)
    assert s["articulation_rate"] == pytest.approx(300)


def test_speech_rate_is_null_without_voiced_frames():
    a = DeliveryAnalyzer(fake_f0())
    utter(a, 0, 1000, syllables=5)
    assert sentence(a)["speech_rate"] is None


def test_f0_median_and_semitones_relative_to_the_session_median():
    values = iter([[(0, 100.0), (20, 100.0), (40, 100.0)], [(0, 200.0)]])
    a = DeliveryAnalyzer(lambda pcm: next(values))
    feed(a, 0, 1000)
    utter(a, 0, 1000, sentence=0)
    feed(a, 2000, 3000)
    utter(a, 2000, 3000, sentence=1)
    first, second = sentence(a, 0), sentence(a, 1)
    assert (first["f0_median_hz"], second["f0_median_hz"]) == (100.0, 200.0)
    assert first["f0_st"] == pytest.approx(0.0)  # session median is 100
    assert second["f0_st"] == pytest.approx(12.0)


def test_f0_fields_are_null_without_f0():
    a = DeliveryAnalyzer(fake_f0())
    feed(a, 0, 1000)
    utter(a, 0, 1000)
    s = sentence(a)
    assert (s["f0_median_hz"], s["f0_st"]) == (None, None)


def test_spectral_balance_uses_only_voiced_frames():
    a = DeliveryAnalyzer(fake_f0())
    feed(a, 0, 500)
    feed(a, 500, 1000, voiced=False, rms=0.0)
    a.observe_utterance(0, 1000, tone(500, 300) + tone(500, 3000), "endpoint", 0, 0, 0)
    s = sentence(a)
    assert s["alpha_ratio_db"] > 20
    assert s["hammarberg_db"] > 20


def test_spectral_balance_is_null_when_pcm_does_not_cover_the_frames():
    a = DeliveryAnalyzer(fake_f0())
    feed(a, 0, 1000)
    utter(a, 0, 1000)
    s = sentence(a)
    assert (s["alpha_ratio_db"], s["hammarberg_db"]) == (None, None)


def windows(a):
    return a.windows()["windows"]


def test_windows_bucket_frames_by_slot_from_the_session_origin():
    a = DeliveryAnalyzer(fake_f0(), origin_ms=1000)
    feed(a, 1000, 12_000)
    utter(a, 1000, 12_000)
    result = a.windows()
    assert result["window_ms"] == 10_000
    first, second = result["windows"]
    assert (first["start_ms"], first["end_ms"], first["voiced_ms"]) == (1000, 11_000, 10_000)
    assert (second["start_ms"], second["end_ms"], second["voiced_ms"]) == (11_000, 21_000, 1000)
    assert (first["observed_ms"], second["observed_ms"]) == (10_000, 1000)
    assert (first["coverage"], second["coverage"]) == (1.0, 1.0)


def test_frame_ending_on_a_boundary_stays_in_its_slot():
    a = DeliveryAnalyzer(fake_f0())
    feed(a, 9_980, 10_020)
    utter(a, 9_980, 10_020)
    first, second = windows(a)
    assert (first["voiced_ms"], second["voiced_ms"]) == (20, 20)


def test_windows_do_not_overlap():
    a = DeliveryAnalyzer(fake_f0())
    feed(a, 0, 30_000)
    utter(a, 0, 30_000)
    rows = windows(a)
    assert [(x["start_ms"], x["end_ms"]) for x in rows] == [
        (0, 10_000),
        (10_000, 20_000),
        (20_000, 30_000),
    ]


def test_syllables_and_disfluencies_split_by_voiced_ms_across_windows():
    a = DeliveryAnalyzer(fake_f0())
    feed(a, 8000, 11_000)
    utter(a, 8000, 11_000, syllables=30, disfluencies=3)
    first, second = windows(a)
    assert (first["syllables"], second["syllables"]) == (pytest.approx(20), pytest.approx(10))
    assert (first["disfluencies"], second["disfluencies"]) == (pytest.approx(2), pytest.approx(1))
    assert first["speech_rate"] == pytest.approx(20 * 60_000 / 2000)
    assert first["articulation_rate"] == pytest.approx(20 * 60_000 / 2000)
    assert first["disfluency_density"] == pytest.approx(2 * 60_000 / 2000)


def test_utterance_counts_follow_its_own_voiced_frames_not_its_span():
    a = DeliveryAnalyzer(fake_f0())
    feed(a, 9000, 10_000)
    feed(a, 10_000, 14_000, voiced=False, rms=0.0)
    feed(a, 14_000, 15_000)
    utter(a, 9000, 15_000, syllables=10)
    first, second = windows(a)
    assert (first["syllables"], second["syllables"]) == (pytest.approx(5), pytest.approx(5))


def test_low_coverage_window_keeps_coverage_but_nulls_features():
    a = DeliveryAnalyzer(fake_f0([100.0, 110.0]))
    feed(a, 0, 5000)
    feed(a, 10_000, 10_500)
    feed(a, 10_500, 20_000, voiced=False, rms=0.0)
    utter(a, 0, 5000, sentence=0, syllables=25)
    utter(a, 10_000, 10_500, sentence=1, syllables=3)
    sparse = windows(a)[1]
    assert (sparse["voiced_ms"], sparse["coverage"]) == (500, 0.05)
    for key in (
        "speech_rate", "articulation_rate", "disfluency_density", "f0_median_hz", "f0_st",
        "pvq", "loudness_dbfs", "loudness_rel_db", "alpha_ratio_db", "hammarberg_db",
    ):  # fmt: skip
        assert sparse[key] is None
    assert windows(a)[0]["speech_rate"] is not None


def test_windows_without_speech_are_still_emitted():
    a = DeliveryAnalyzer(fake_f0())
    feed(a, 0, 2000)
    feed(a, 2000, 30_000, voiced=False, rms=0.0)
    utter(a, 0, 2000, syllables=8)
    rows = windows(a)
    assert len(rows) == 3
    for row in rows[1:]:
        assert (row["voiced_ms"], row["coverage"], row["syllables"]) == (0, 0.0, 0)
        assert row["speech_rate"] is None
        assert row["pause_count"] == 0


def test_no_frames_means_no_windows():
    assert DeliveryAnalyzer(fake_f0()).windows() == {
        "window_ms": 10_000,
        "baseline": {},
        "windows": [],
    }


def test_window_acoustic_features_and_relative_values():
    values = iter([[(1000, 100.0), (2500, 100.0)], [(1000, 200.0), (2500, 200.0)]])
    a = DeliveryAnalyzer(lambda pcm: next(values))
    feed(a, 0, 4000, rms=0.1)
    utter(a, 0, 4000, sentence=0)
    feed(a, 10_000, 14_000, rms=0.01)
    utter(a, 10_000, 14_000, sentence=1)
    first, second = windows(a)
    assert (first["f0_median_hz"], second["f0_median_hz"]) == (100.0, 200.0)
    # session F0 median is the pooled median of 100 and 200 Hz frames, i.e. 150 Hz
    assert first["f0_st"] == pytest.approx(12 * math.log2(100 / 150))
    assert second["f0_st"] == pytest.approx(12 * math.log2(200 / 150))
    assert first["pvq"] == pytest.approx(0.0)
    assert (first["loudness_dbfs"], second["loudness_dbfs"]) == (
        pytest.approx(-20),
        pytest.approx(-40),
    )
    # baseline is the median of the two eligible windows: -30 dBFS
    assert first["loudness_rel_db"] == pytest.approx(10)
    assert second["loudness_rel_db"] == pytest.approx(-10)


def test_f0_offsets_are_converted_to_absolute_session_time():
    a = DeliveryAnalyzer(lambda pcm: [(1000, 100.0), (2500, 300.0)])
    feed(a, 8000, 12_000)
    utter(a, 8000, 12_000)
    first, second = windows(a)
    assert (first["f0_median_hz"], second["f0_median_hz"]) == (100.0, 300.0)


def test_window_spectral_balance_from_voiced_frames():
    a = DeliveryAnalyzer(fake_f0())
    feed(a, 0, 2000)
    a.observe_utterance(0, 2000, tone(2000, 300), "endpoint", 0, 0, 0)
    row = windows(a)[0]
    assert row["alpha_ratio_db"] > 20
    assert row["hammarberg_db"] > 20


def test_pause_counts_in_the_window_where_it_starts():
    a = DeliveryAnalyzer(fake_f0())
    feed(a, 8000, 9800)
    feed(a, 9800, 10_400, voiced=False, rms=0.0)
    feed(a, 10_400, 12_000)
    utter(a, 8000, 12_000)
    first, second = windows(a)
    assert (first["pause_count"], second["pause_count"]) == (1, 0)


def test_short_gaps_are_not_window_pauses():
    a = DeliveryAnalyzer(fake_f0())
    feed(a, 0, 1000)
    feed(a, 1000, 1200, voiced=False, rms=0.0)
    feed(a, 1200, 2000)
    utter(a, 0, 2000)
    assert windows(a)[0]["pause_count"] == 0


def test_window_baseline_is_median_over_windows_with_1s_voiced():
    a = DeliveryAnalyzer(fake_f0())
    for index, (length, syllables) in enumerate([(2000, 10), (4000, 40), (6000, 90), (500, 999)]):
        start = index * 10_000
        feed(a, start, start + length)
        utter(a, start, start + length, sentence=index, syllables=syllables)
    baseline = a.windows()["baseline"]
    assert baseline["articulation_rate"] == pytest.approx(600)
    assert baseline["voiced_ms"] == 4000
    assert baseline["speech_rate"] == pytest.approx(240)
    assert "coverage" not in baseline and "start_ms" not in baseline


def build_mixed():
    values = iter([[(100, 100.0), (200, 120.0)], [(100, 200.0)]])
    a = DeliveryAnalyzer(lambda pcm: next(values))
    feed(a, 0, 4000)
    utter(a, 0, 4000, sentence=0, syllables=20, disfluencies=1)
    feed(a, 12_000, 16_000)
    utter(a, 12_000, 16_000, sentence=1, syllables=24, disfluencies=2)
    return a


def test_report_and_windows_do_not_depend_on_call_order():
    one, two = build_mixed(), build_mixed()
    report_first = one.report()
    windows_after = one.windows()
    windows_first = two.windows()
    report_after = two.report()
    assert report_first == report_after
    assert windows_after == windows_first
    assert one.windows() == windows_after
    assert one.report() == report_first


def test_partial_last_window_is_normalised_by_its_observed_span():
    a = DeliveryAnalyzer(fake_f0())
    feed(a, 0, 23_000)
    utter(a, 0, 23_000, syllables=115)  # constant 300 syllables/min
    rows = windows(a)
    assert [x["observed_ms"] for x in rows] == [10_000, 10_000, 3000]
    assert rows[2]["speech_rate"] == pytest.approx(300)
    assert rows[2]["coverage"] == pytest.approx(1.0)
    assert rows[0]["speech_rate"] == pytest.approx(300)


def test_late_start_window_is_normalised_by_its_observed_span():
    a = DeliveryAnalyzer(fake_f0(), origin_ms=0)
    feed(a, 7000, 20_000)
    utter(a, 7000, 20_000, syllables=65)  # 300 syllables/min
    first, second = windows(a)
    assert first["observed_ms"] == 3000
    assert first["speech_rate"] == pytest.approx(300)
    assert first["coverage"] == pytest.approx(1.0)
    assert second["observed_ms"] == 10_000


def test_observed_span_is_not_a_baseline_feature():
    a = DeliveryAnalyzer(fake_f0())
    feed(a, 0, 3000)
    utter(a, 0, 3000, syllables=15)
    assert "observed_ms" not in a.windows()["baseline"]


def test_spectral_balance_aligns_pcm_to_a_non_zero_utterance_start():
    a = DeliveryAnalyzer(fake_f0())
    feed(a, 5000, 5200, voiced=False, rms=0.0)
    feed(a, 5200, 5700)
    a.observe_utterance(5000, 5700, tone(200, 3000) + tone(500, 300), "endpoint", 0, 0, 0)
    s = sentence(a)
    assert s["alpha_ratio_db"] > 20
    assert s["hammarberg_db"] > 20


def test_zero_length_frames_give_null_rates_instead_of_dividing_by_zero():
    a = DeliveryAnalyzer(extract_f0=fake_f0())
    a.observe_frame(100, 100, 0.1, False)
    row = a.windows()["windows"][0]
    assert row["observed_ms"] == 0
    assert row["coverage"] is None and row["speech_rate"] is None
    assert row["articulation_rate"] is None and row["disfluency_density"] is None


def test_window_coverage_never_exceeds_one():
    a = DeliveryAnalyzer(extract_f0=fake_f0())
    a.observe_frame(9990, 10010, 0.1, True)
    utter(a, 9990, 10010, syllables=1)
    first = a.windows()["windows"][0]
    assert first["voiced_ms"] == 20 and first["observed_ms"] == 10
    assert first["coverage"] == 1.0
