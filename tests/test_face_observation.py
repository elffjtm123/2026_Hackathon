from types import SimpleNamespace

import numpy as np
import pytest

from app.ai import uniface_gaze


def face_points():
    points = [SimpleNamespace(x=0.3 if i % 2 else 0.7, y=0.3 if i % 3 else 0.7) for i in range(478)]
    for indices in [(33, 160, 158, 133, 153, 144), (362, 385, 387, 263, 373, 380)]:
        for index, (x, y) in zip(
            indices,
            [(0.4, 0.4), (0.42, 0.38), (0.46, 0.38), (0.48, 0.4), (0.46, 0.42), (0.42, 0.42)],
            strict=True,
        ):
            points[index] = SimpleNamespace(x=x, y=y)
    return points


def test_pose_missing_does_not_invent_values():
    from app.ai import face_observation as module

    assert module.head_pose_from_matrix(None) == {"yaw": None, "pitch": None, "roll": None}
    assert module.head_pose_from_matrix(np.full((4, 4), np.nan))["yaw"] is None


@pytest.mark.parametrize("axis,key", [(0, "pitch"), (1, "yaw")])
def test_synthetic_pose_matrix_maps_axes(axis, key):
    from app.ai import face_observation as module

    angle = np.radians(-20)
    c, s = np.cos(angle), np.sin(angle)
    matrix = np.eye(4)
    matrix[:3, :3] = (
        [[1, 0, 0], [0, c, -s], [0, s, c]] if axis == 0 else [[c, 0, s], [0, 1, 0], [-s, 0, c]]
    )
    assert module.head_pose_from_matrix(matrix)[key] == pytest.approx(20)


@pytest.mark.parametrize(
    "case,flag",
    [
        ("none", "no_face"),
        ("multiple", "multiple_faces"),
        ("blink", "eyes_closed"),
        ("small", "face_too_small"),
        ("blur", "blurry"),
        ("dark", "too_dark"),
    ],
)
def test_bad_face_input_is_flagged(case, flag):
    from app.ai import face_observation as module

    frame = np.random.default_rng(1).integers(60, 180, (200, 200, 3), dtype=np.uint8)
    points = face_points()
    faces = [points]
    if case == "none":
        faces = []
    if case == "multiple":
        faces = [points, points]
    if case == "small":
        for point in points:
            point.x, point.y = 0.5 + (point.x - 0.5) / 10, 0.5 + (point.y - 0.5) / 10
    if case == "blink":
        for index in [160, 158, 153, 144, 385, 387, 373, 380]:
            points[index].y = 0.4
    if case == "blur":
        frame[:] = 120
    if case == "dark":
        frame[:] = 0
    result = SimpleNamespace(face_landmarks=faces, facial_transformation_matrixes=[np.eye(4)])
    observation = module.observation_from_result(frame, result, 100)
    assert flag in observation.quality_flags


@pytest.mark.asyncio
async def test_default_crop_path_does_not_call_retinaface():
    from app.modules.gaze import service

    class Observer:
        def observe_face(self, frame, timestamp_ms):
            return service.GazeObservation(
                True,
                {"yaw": 0.0, "pitch": 0.0, "roll": 0.0},
                {"yaw": None, "pitch": None},
                None,
                [],
                timestamp_ms,
                bbox=(20, 10, 180, 190),
            )

        def reset(self):
            pass

        def close(self):
            pass

    estimator = SimpleNamespace(estimate=lambda crop: SimpleNamespace(yaw=0.1, pitch=0.2))
    adapter = uniface_gaze.UniFaceGazeAdapter(
        estimator=estimator,
        face_observer=Observer(),
        decoder=lambda payload: np.ones((200, 200, 3), dtype=np.uint8),
    )
    from uuid import uuid4

    from app.ai.base import MediaPayload

    result = await adapter.infer(MediaPayload(uuid4(), 0, b"jpeg"))
    assert result.metrics["head_pose"]["yaw"] == 0
    assert result.metrics["gaze_angles"]["yaw"] > 0
    adapter.close()


@pytest.mark.asyncio
async def test_close_waits_for_native_observation_before_destroying_landmarker():
    import asyncio
    import threading
    from uuid import uuid4

    from app.ai.base import MediaPayload
    from app.modules.gaze.service import GazeObservation

    entered, release, closed = threading.Event(), threading.Event(), threading.Event()

    class Observer:
        def reset(self):
            pass

        def observe_face(self, frame, timestamp_ms):
            entered.set()
            release.wait(2)
            return GazeObservation(
                False,
                {"yaw": None, "pitch": None, "roll": None},
                {"yaw": None, "pitch": None},
                None,
                ["no_face"],
                timestamp_ms,
            )

        def close(self):
            closed.set()

    adapter = uniface_gaze.UniFaceGazeAdapter(
        estimator=object(),
        face_observer=Observer(),
        decoder=lambda payload: np.ones((10, 10, 3), dtype=np.uint8),
    )
    task = asyncio.create_task(adapter.infer(MediaPayload(uuid4(), 0, b"jpeg")))
    await asyncio.to_thread(entered.wait, 1)
    adapter.close()
    try:
        assert not closed.is_set()
    finally:
        release.set()
        await task
    assert await asyncio.to_thread(closed.wait, 1)
