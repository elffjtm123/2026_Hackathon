"""Live model-comparison bookkeeping: events in, one report["comparison"] summary out."""

from app.ai.base import AIResult
from app.realtime.experiment_recorder import ExperimentRecorder


def result(source, timestamp_ms, latency_ms=None):
    return AIResult(source, timestamp_ms, "info", "", {}, latency_ms=latency_ms)


def test_summary_of_an_empty_session_keeps_the_report_shape():
    recorder = ExperimentRecorder({"model_id": "qwen_q8", "mode": "presentation"})
    assert recorder.summary(dropped_video_frames=0) == {
        "model_id": "qwen_q8",
        "mode": "presentation",
        "performance": {},
        "errors": {},
        "audio_queue_peak": 0,
        "dropped_video_frames": 0,
    }


def test_performance_averages_measured_latency_and_tracks_oldest_result():
    recorder = ExperimentRecorder({"model_id": "qwen_q8"})
    recorder.record_result(result("speech_rate", 1000, latency_ms=100), now_ms=1500)
    recorder.record_result(result("speech_rate", 2000, latency_ms=None), now_ms=2100)
    recorder.record_result(result("speech_rate", 3000, latency_ms=201), now_ms=3050)
    recorder.record_result(result("gaze", 3000), now_ms=3010)
    performance = recorder.summary(dropped_video_frames=0)["performance"]
    assert performance == {
        "speech_rate": {
            "observations": 3,
            "measured_latency_count": 2,
            "average_inference_ms": 150.5,
            "max_result_age_ms": 500,
        },
        "gaze": {
            "observations": 1,
            "measured_latency_count": 0,
            "average_inference_ms": None,
            "max_result_age_ms": 10,
        },
    }


def test_errors_queue_peak_and_dropped_frames_are_counted():
    recorder = ExperimentRecorder({"model_id": "zipformer_int8"})
    for code in ["AUDIO_QUEUE_FULL", "MEDIA_SEQUENCE_GAP", "AUDIO_QUEUE_FULL"]:
        recorder.record_error(code)
    for depth in [1, 4, 2]:
        recorder.record_audio_queue(depth)
    summary = recorder.summary(dropped_video_frames=7)
    assert summary["errors"] == {"AUDIO_QUEUE_FULL": 2, "MEDIA_SEQUENCE_GAP": 1}
    assert summary["audio_queue_peak"] == 4
    assert summary["dropped_video_frames"] == 7


def test_info_is_what_session_ready_shows_and_can_be_annotated():
    recorder = ExperimentRecorder({"model_id": "qwen_q8", "gaze": {"status": "loading"}})
    recorder.annotate(gaze={"status": "ready"})
    assert recorder.info == {"model_id": "qwen_q8", "gaze": {"status": "ready"}}
    assert recorder.summary(dropped_video_frames=0)["gaze"] == {"status": "ready"}


def test_summary_is_a_snapshot_not_a_live_view():
    recorder = ExperimentRecorder({"model_id": "qwen_q8"})
    recorder.record_error("X")
    first = recorder.summary(dropped_video_frames=0)
    recorder.record_error("X")
    recorder.record_result(result("gaze", 0), now_ms=0)
    assert first["errors"] == {"X": 1}
    assert first["performance"] == {}
