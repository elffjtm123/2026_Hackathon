"""Practice sessions and STT comparison runs share the CPU models; only one side may run."""

from types import SimpleNamespace

import pytest

from app.services.experiment_exclusion import ExperimentExclusion, ExperimentRunning


def exclusion(**overrides):
    parts = {
        "experiments": SimpleNamespace(busy=False),
        "live_speech": SimpleNamespace(busy=False),
        "execution": SimpleNamespace(busy=False),
        "pipelines": SimpleNamespace(busy=False),
        "webrtc": SimpleNamespace(busy=False),
    }
    parts.update(overrides)
    return ExperimentExclusion(**parts)


def test_idle_service_allows_both_sides():
    subject = exclusion()
    assert not subject.experiment_blocked
    with subject.practice_connection():
        assert subject.experiment_blocked
    assert not subject.experiment_blocked


@pytest.mark.parametrize(
    "override",
    [
        {"experiments": SimpleNamespace(busy=True)},
        {"live_speech": SimpleNamespace(busy=True)},
        {"execution": SimpleNamespace(busy=True)},
        {"pipelines": SimpleNamespace(busy=True)},
        {"webrtc": SimpleNamespace(busy=True)},
    ],
    ids=["experiment", "live-theme", "model-owner", "pipeline", "webrtc"],
)
def test_any_running_work_blocks_a_new_experiment(override):
    assert exclusion(**override).experiment_blocked


def test_service_without_model_execution_does_not_block():
    assert not exclusion(execution=None).experiment_blocked


def test_open_practice_connection_blocks_experiments_until_it_closes():
    subject = exclusion()
    with subject.practice_connection():
        assert subject.experiment_blocked
    assert not subject.experiment_blocked


def test_connection_count_is_released_when_the_session_fails():
    subject = exclusion()
    with pytest.raises(RuntimeError):
        with subject.practice_connection():
            raise RuntimeError("negotiation failed")
    assert not subject.experiment_blocked


@pytest.mark.parametrize(
    "override",
    [{"experiments": SimpleNamespace(busy=True)}, {"live_speech": SimpleNamespace(busy=True)}],
    ids=["experiment", "live-theme"],
)
def test_running_experiment_refuses_practice_without_counting(override):
    subject = exclusion(**override)
    with pytest.raises(ExperimentRunning):
        with subject.practice_connection():
            pass
    next(iter(override.values())).busy = False  # the experiment finishes
    assert not subject.experiment_blocked


def test_model_execution_is_busy_while_anything_owns_the_models():
    from app.ai.model_execution import ModelExecution

    execution = ModelExecution(runtime=None)
    assert not execution.busy
    execution.reserve_summary()
    assert execution.busy
    execution.release_summary()
    assert not execution.busy


def test_pipeline_registry_is_busy_while_a_session_pipeline_exists():
    from app.realtime.registry import PipelineRegistry

    registry = PipelineRegistry(*(None,) * 5)
    assert not registry.busy
    registry.pipelines["session"] = object()  # type: ignore[assignment]
    assert registry.busy


def test_webrtc_manager_is_busy_only_with_an_open_peer():
    from app.core.config import Settings
    from app.realtime.webrtc import WebRTCManager

    manager = WebRTCManager(Settings())
    manager.connections["session"] = set()  # type: ignore[index]
    assert not manager.busy
    manager.connections["session"].add(object())  # type: ignore[index, arg-type]
    assert manager.busy
