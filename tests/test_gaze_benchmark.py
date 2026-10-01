from scripts.benchmark_gaze import summarize


def test_unlabeled_or_empty_benchmark_is_not_reported_as_accuracy():
    result = summarize([])
    assert result["binary_f1"] is None
    assert result["macro_f1"] is None
    result = summarize(
        [{"ground_truth": None, "prediction": "unknown", "face_detected": False, "latency_ms": 10}]
    )
    assert result["binary_f1"] is None
