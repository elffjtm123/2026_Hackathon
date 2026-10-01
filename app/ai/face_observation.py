import math
from pathlib import Path
from typing import Any

import numpy as np

from app.modules.gaze.service import GazeObservation

FACE_MODEL_SHA256 = "64184e229b263107bc2b804c6625db1341ff2bb731874b0bcc2fe6544e0bc9ff"


def head_pose_from_matrix(matrix: Any) -> dict[str, float | None]:
    missing: dict[str, float | None] = {"yaw": None, "pitch": None, "roll": None}
    if matrix is None:
        return missing
    matrix = np.asarray(matrix, dtype=float)
    if matrix.shape != (4, 4) or not np.isfinite(matrix).all():
        return missing
    rotation = matrix[:3, :3]
    scales = np.linalg.norm(rotation, axis=0)
    if np.min(scales) < 1e-6:
        return missing
    rotation = rotation / scales
    if np.linalg.det(rotation) <= 0 or not np.allclose(rotation.T @ rotation, np.eye(3), atol=0.05):
        return missing
    # MediaPipe right-handed geometry: camera looks -Z. User-right/up = -Ry/-Rx.
    pitch = -math.atan2(float(rotation[2, 1]), float(rotation[2, 2]))
    yaw = math.asin(float(np.clip(rotation[2, 0], -1, 1)))
    roll = math.atan2(float(rotation[1, 0]), float(rotation[0, 0]))
    return {"yaw": math.degrees(yaw), "pitch": math.degrees(pitch), "roll": math.degrees(roll)}


def observation_from_result(
    frame: Any,
    result: Any,
    timestamp_ms: int,
    *,
    min_area: float = 0.02,
    min_brightness: float = 30,
    max_brightness: float = 235,
    min_sharpness: float = 40,
    min_eye_ratio: float = 0.15,
) -> GazeObservation:
    import cv2

    empty: dict[str, float | None] = {"yaw": None, "pitch": None, "roll": None}
    faces = result.face_landmarks
    if len(faces) != 1:
        return GazeObservation(
            False,
            empty,
            {"yaw": None, "pitch": None},
            None,
            ["no_face" if not faces else "multiple_faces"],
            timestamp_ms,
        )
    h, w = frame.shape[:2]
    points = np.array([(p.x * w, p.y * h) for p in faces[0]], dtype=float)
    if len(points) < 468 or not np.isfinite(points).all():
        return GazeObservation(
            True, empty, {"yaw": None, "pitch": None}, None, ["invalid_landmarks"], timestamp_ms
        )
    x1, y1 = np.maximum(0, points.min(axis=0)).astype(int)
    x2, y2 = np.minimum([w, h], points.max(axis=0)).astype(int)
    bbox = (int(x1), int(y1), int(x2), int(y2))
    crop = frame[y1:y2, x1:x2]
    if crop.size == 0:
        return GazeObservation(
            True, empty, {"yaw": None, "pitch": None}, None, ["invalid_crop"], timestamp_ms
        )
    gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
    area = (x2 - x1) * (y2 - y1) / float(w * h)
    brightness, sharpness = float(gray.mean()), float(cv2.Laplacian(gray, cv2.CV_64F).var())
    ratios = []
    for indices in [(33, 160, 158, 133, 153, 144), (362, 385, 387, 263, 373, 380)]:
        p = points[list(indices)]
        ratios.append(
            float(
                (np.linalg.norm(p[1] - p[5]) + np.linalg.norm(p[2] - p[4]))
                / max(1e-6, float(2 * np.linalg.norm(p[0] - p[3])))
            )
        )
    flags = []
    if area < min_area:
        flags.append("face_too_small")
    if brightness < min_brightness:
        flags.append("too_dark")
    if brightness > max_brightness:
        flags.append("too_bright")
    if sharpness < min_sharpness:
        flags.append("blurry")
    if min(ratios) < min_eye_ratio:
        flags.append("eyes_closed")
    matrices = result.facial_transformation_matrixes
    pose = head_pose_from_matrix(matrices[0] if len(matrices) else None)
    if pose["yaw"] is None:
        flags.append("pose_unavailable")
    return GazeObservation(
        True,
        pose,
        {"yaw": None, "pitch": None},
        None,
        flags,
        timestamp_ms,
        bbox,
        {
            "face_area_ratio": float(area),
            "brightness": brightness,
            "sharpness": sharpness,
            "eye_ratio": min(ratios),
        },
    )


class FaceObserver:
    def __init__(self, asset_path: str) -> None:
        import hashlib

        import mediapipe as mp

        asset = Path(asset_path)
        if not asset.is_file():
            raise FileNotFoundError("FACE_LANDMARKER_ASSET_MISSING")
        if hashlib.sha256(asset.read_bytes()).hexdigest() != FACE_MODEL_SHA256:
            raise ValueError("FACE_LANDMARKER_CHECKSUM_MISMATCH")
        self.mp = mp
        options = mp.tasks.vision.FaceLandmarkerOptions(
            base_options=mp.tasks.BaseOptions(
                model_asset_path=str(asset), delegate=mp.tasks.BaseOptions.Delegate.CPU
            ),
            running_mode=mp.tasks.vision.RunningMode.IMAGE,
            num_faces=2,
            output_facial_transformation_matrixes=True,
        )
        self.landmarker = mp.tasks.vision.FaceLandmarker.create_from_options(options)
        self.reset()

    def reset(self) -> None:
        self.previous_bbox: tuple[int, int, int, int] | None = None
        self.previous_shape: tuple[int, ...] | None = None

    def observe_face(self, frame: Any, timestamp_ms: int) -> GazeObservation:
        import cv2

        image = self.mp.Image(
            image_format=self.mp.ImageFormat.SRGB, data=cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        )
        observation = observation_from_result(frame, self.landmarker.detect(image), timestamp_ms)
        if self.previous_shape is not None and self.previous_shape != frame.shape:
            observation.quality_flags.append("camera_changed")
        if observation.bbox is not None and self.previous_bbox is not None:
            a, b = observation.bbox, self.previous_bbox
            intersect = max(0, min(a[2], b[2]) - max(a[0], b[0])) * max(
                0, min(a[3], b[3]) - max(a[1], b[1])
            )
            union = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - intersect
            if intersect / max(1, union) < 0.3:
                observation.quality_flags.append("face_changed")
        if observation.bbox is not None:
            self.previous_bbox = observation.bbox
        self.previous_shape = frame.shape
        return observation

    def close(self) -> None:
        self.landmarker.close()
