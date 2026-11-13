"""Practice sessions and STT comparison runs share the CPU models; only one side may run."""

import contextlib
from collections.abc import Iterator
from typing import Protocol


class ExperimentRunning(Exception):
    """A batch comparison or a live model-theme lease is holding the models."""


class Busy(Protocol):
    """Anything that can say whether it is currently doing model work."""

    @property
    def busy(self) -> bool: ...


class ExperimentExclusion:
    def __init__(
        self,
        *,
        experiments: Busy,
        live_speech: Busy,
        execution: Busy | None,
        pipelines: Busy,
        webrtc: Busy,
    ) -> None:
        self._experiments, self._live_speech = experiments, live_speech
        self._execution, self._pipelines, self._webrtc = execution, pipelines, webrtc
        # Practice WebSockets and in-flight WebRTC offers; counted before any model is touched.
        self._open_practice_connections = 0

    @property
    def experiment_blocked(self) -> bool:
        """True while a comparison job may not start (another job or any practice work)."""
        return bool(
            self._experiments.busy
            or self._open_practice_connections
            or self._live_speech.busy
            or (self._execution is not None and self._execution.busy)
            or self._pipelines.busy
            or self._webrtc.busy
        )

    @contextlib.contextmanager
    def practice_connection(self) -> Iterator[None]:
        """Hold one practice connection open; raises ExperimentRunning without counting."""
        if self._experiments.busy or self._live_speech.busy:
            raise ExperimentRunning()
        self._open_practice_connections += 1
        try:
            yield
        finally:
            self._open_practice_connections -= 1
