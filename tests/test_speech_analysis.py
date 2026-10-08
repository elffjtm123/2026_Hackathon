import pytest


def final(text, *, utterance_id="u1", start_ms=0, end_ms=6000, voiced_ms=6000):
    from app.modules.speech.segments import FinalUtterance

    return FinalUtterance(utterance_id, start_ms, end_ms, voiced_ms, text)


def test_hangul_syllables_exclude_latin_and_digits_and_380_is_fast():
    from app.modules.speech.analysis import analyze_utterance

    result = analyze_utterance(final("가" * 38 + " API 123"))
    assert result.syllable_count == 38
    assert result.syllables_per_minute == 380
    assert result.pace == "fast"


@pytest.mark.parametrize("text", ["", "API 123"])
def test_non_korean_or_silence_has_unknown_korean_rate(text):
    from app.modules.speech.analysis import analyze_utterance

    result = analyze_utterance(final(text))
    assert result.syllables_per_minute is None
    assert result.pace == "unknown"


def test_filler_boundaries_and_repetitions_are_separate():
    from app.modules.speech.analysis import analyze_utterance

    result = analyze_utterance(final("음, 음 어어어 어머니 그 그 기본적으로요"))
    assert result.filler_counts == {"음": 2, "어": 1, "그": 2}
    assert result.repeat_count == 2
    assert "(말더듬)" not in result.filler_counts


def test_rate_window_needs_evidence_and_weights_counts_over_voiced_time():
    from app.modules.speech.analysis import SpeechRateWindow, analyze_utterance

    window = SpeechRateWindow()
    a = final("가" * 5, end_ms=1000, voiced_ms=1000)
    window.add(a, analyze_utterance(a))
    assert window.snapshot(1000).pace == "unknown"
    b = final("나" * 15, utterance_id="u2", start_ms=1000, end_ms=4000, voiced_ms=3000)
    window.add(b, analyze_utterance(b))
    assert window.snapshot(4000).syllables_per_minute == 300
    assert window.snapshot(15000).pace == "unknown"


def test_same_sentence_distinct_ids_is_kept_but_retransmission_counts_once():
    from app.ai.base import AIResult
    from app.modules.speech.analysis import analyze_utterance
    from app.realtime.aggregator import FeedbackAggregator

    aggregator = FeedbackAggregator()
    for identity in ["u1", "u1", "u2"]:
        item = final("음 안녕하세요", utterance_id=identity, voiced_ms=1000, end_ms=1000)
        metrics = {**analyze_utterance(item).as_dict(), "utterance_id": identity, "revision": 1}
        aggregator.add(AIResult("speech_rate", 0, "info", "ok", metrics, item.text, True))
    report = aggregator.report()
    assert report["transcript"] == "음 안녕하세요 음 안녕하세요"
    assert report["filler_word_counts"] == {"음": 2}
    assert report["average_syllables_per_minute"] == 360
    assert len(report["timeline"]) == 2


def test_disabled_modules_do_not_analyze(monkeypatch):
    from app.modules.speech import analysis

    def fail(_text):
        raise AssertionError("disabled filler analysis must not run")

    monkeypatch.setattr(analysis, "filler_counts", fail)
    result = analysis.analyze_utterance(
        final("음 안녕하세요"), rate_enabled=False, fillers_enabled=False
    )
    assert result.pace == "unknown"
    assert result.filler_counts == {}


def test_report_rate_uses_counts_over_voiced_time_not_average_of_rates():
    from app.ai.base import AIResult
    from app.modules.speech.analysis import analyze_utterance
    from app.realtime.aggregator import FeedbackAggregator

    aggregator = FeedbackAggregator()
    for item in [
        final("가" * 5, end_ms=1000, voiced_ms=1000),
        final("나" * 15, utterance_id="u2", start_ms=1000, end_ms=6000, voiced_ms=5000),
    ]:
        metrics = {**analyze_utterance(item).as_dict(), "utterance_id": item.utterance_id}
        aggregator.add(
            AIResult("speech_rate", item.start_ms, "info", "ok", metrics, item.text, True)
        )
    assert aggregator.report()["average_syllables_per_minute"] == 200


def test_multi_word_fillers_are_not_counted_again_as_single_words():
    from app.modules.speech.analysis import analyze_utterance

    result = analyze_utterance(final("뭔가 좀 솔직히 말해서"))
    assert result.filler_counts == {"뭔가 좀": 1, "솔직히 말해서": 1}


def test_standalone_analyzers_reuse_korean_rate_and_filler_rules():
    from stt import FillerWordAnalyzer, SpeechRateAnalyzer

    rate = SpeechRateAnalyzer().analyze("가" * 38 + " API 123", 6)
    assert rate["cpm"] == 380
    assert rate["level"] == "FAST"
    fillers = FillerWordAnalyzer().analyze("음, 그 그 뭔가 좀")
    assert fillers["counts"] == {"음": 1, "그": 2, "뭔가 좀": 1}
    assert fillers["repeat_count"] == 1


def test_warning_episodes_are_not_counted_per_event_and_silence_resets_episode():
    from app.ai.base import AIResult
    from app.realtime.aggregator import FeedbackAggregator

    aggregator = FeedbackAggregator()
    for identity, pace in [("u1", "fast"), ("u2", "fast"), (None, "unknown"), ("u3", "fast")]:
        metrics = {"pace": pace}
        if identity:
            metrics["utterance_id"] = identity
        aggregator.add(
            AIResult(
                "speech_rate", 0, "info", "ok", metrics, "가" if identity else None, bool(identity)
            )
        )
    assert aggregator.report()["speech_rate_metrics"]["warning_episode_count"] == 2
