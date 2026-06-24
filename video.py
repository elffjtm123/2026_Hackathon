"""
AI 발표/면접 시선 분석 v3
AI Hub 데이터셋 학습 + 실시간 웹캠 + UP/DOWN 캘리브레이션 보정 버전

설치:
    pip install opencv-python mediapipe numpy scikit-learn joblib tqdm

실행:
    python trained_camera_gaze_v3_downfix.py

중요:
1. 실행 직후 카메라 창이 뜨면 처음 2초 정도는 반드시 정면을 본다.
2. 그 2초 동안의 얼굴/눈 위치를 정면 기준값으로 저장한다.
3. 이후 기준값 대비 위/아래/좌우로 얼마나 벗어났는지로 Gaze를 판단한다.
4. q 키를 누르면 종료된다.
"""

import os
import re
import json
import time
import xml.etree.ElementTree as ET
from pathlib import Path
from dataclasses import dataclass, field
from typing import Optional, Dict, Any, List, Tuple
from collections import Counter, deque

import csv
import cv2
import numpy as np
from tqdm import tqdm

try:
    import mediapipe as mp
except ImportError:
    print("mediapipe가 설치되어 있지 않습니다.")
    print("pip install mediapipe")
    raise

try:
    from sklearn.ensemble import RandomForestClassifier
    from sklearn.preprocessing import LabelEncoder
    from sklearn.model_selection import train_test_split
    from sklearn.metrics import accuracy_score, classification_report
    import joblib
    SKLEARN_AVAILABLE = True
except ImportError:
    SKLEARN_AVAILABLE = False
    print("scikit-learn 또는 joblib이 없습니다. rule-based 방식으로만 동작합니다.")


# ============================================================
# 경로 설정
# ============================================================
OUTPUT_DIR = r"C:\Users\yoonh\OneDrive\바탕 화면\2026_Hackathon\Sample\outputs"
MODEL_PATH = os.path.join(OUTPUT_DIR, "gaze_model_v3.pkl")
LABEL_ENCODER_PATH = os.path.join(OUTPUT_DIR, "gaze_label_encoder_v3.pkl")
os.makedirs(OUTPUT_DIR, exist_ok=True)

# AI Hub 원천 데이터셋 경로 (없으면 건너뜀)
_BASE_DIR = r"C:\Users\yoonh\OneDrive\바탕 화면\2026_Hackathon\Sample"
DISPLAY_GAZE_LABEL_PATH          = os.path.join(_BASE_DIR, "라벨링데이터", "DisplayGaze")
DISPLAY_GAZE_LABEL_PATH_FALLBACK = os.path.join(_BASE_DIR, "DisplayGaze")
DISPLAY_GAZE_IMAGE_PATH          = os.path.join(_BASE_DIR, "원천데이터", "DisplayGaze")
EYE_MOVEMENT_LABEL_PATH          = os.path.join(_BASE_DIR, "라벨링데이터", "EyeMovement")
EYE_MOVEMENT_IMAGE_PATH          = os.path.join(_BASE_DIR, "원천데이터", "EyeMovement")

# feature_extract.py 출력 CSV 경로 (video.py와 같은 디렉터리)
_SAMPLE_DIR      = os.path.dirname(os.path.abspath(__file__))
JSON_RGB_CSV     = os.path.join(_SAMPLE_DIR, "features_json_rgb.csv")
MPIIFACEGAZE_CSV = os.path.join(_SAMPLE_DIR, "features_mpiifacegaze.csv")

FORCE_RETRAIN = False


# ============================================================
# 기본 설정
# ============================================================

CAMERA_INDEX = 0
FRAME_WIDTH = 640
FRAME_HEIGHT = 480

MAX_DISPLAY_JSON = 1000
MAX_EYE_XML = 30
MAX_FRAMES_PER_XML = 40

GAZE_LABELS = ["CENTER", "LEFT", "RIGHT", "UP", "DOWN", "UNKNOWN"]

# 데이터셋 라벨 변환 기준
YAW_THRESHOLD = 0.20
PITCH_THRESHOLD = 0.20
IRIS_OFFSET_THRESH = 0.25

# 학습 데이터에서 DOWN/UP이 적을 때 보강
AUGMENT_DOWN_N = 500
AUGMENT_UP_N = 250

# 실시간 웹캠 캘리브레이션 기준
CALIBRATION_FRAMES = 60
SMOOTHING_WINDOW = 8

# 아래/위는 민감하게, 좌우는 과검출 줄이기 위해 둔하게
DOWN_HEAD_DELTA = 0.13
DOWN_EYE_DELTA = 0.07
UP_HEAD_DELTA = -0.13
UP_EYE_DELTA = -0.07

SIDE_HEAD_DELTA = 0.12
SIDE_EYE_DELTA = 0.10

# 피드백 기준
CENTER_GOOD_THRESHOLD = 0.70
CENTER_NORMAL_THRESHOLD = 0.50
DOWN_WARNING_THRESHOLD = 0.20
SIDE_WARNING_THRESHOLD = 0.30
NO_FACE_WARNING_THRESHOLD = 0.15

# MediaPipe Face Mesh landmark index
IRIS_GROUP_A = list(range(468, 473))
IRIS_GROUP_B = list(range(473, 478))
EYE_OUTER_LEFT = 33
EYE_INNER_LEFT = 133
EYE_INNER_RIGHT = 362
EYE_OUTER_RIGHT = 263
NOSE_TIP = 1
CHIN = 152
EAR_LEFT = 234
EAR_RIGHT = 454


# ============================================================
# 유틸
# ============================================================

def imread_unicode(path: str) -> Optional[np.ndarray]:
    """한글/공백 경로 이미지 읽기."""
    try:
        with open(path, "rb") as f:
            buf = np.frombuffer(f.read(), dtype=np.uint8)
        return cv2.imdecode(buf, cv2.IMREAD_COLOR)
    except Exception:
        return None


def safe_float(v):
    try:
        return float(v) if v is not None else None
    except Exception:
        return None


# ============================================================
# Dataset 1: 디스플레이 중심 안구 움직임 JSON 파서
# ============================================================

def parse_display_json(json_path: str) -> Dict[str, Any]:
    result = {
        "source": "display_json", "path": json_path,
        "yaw": None, "pitch": None, "roll": None, "gaze_point": None,
        "left_center": None, "right_center": None,
        "left_iris_cx": None, "left_iris_cy": None, "left_iris_rx": None,
        "right_iris_cx": None, "right_iris_cy": None, "right_iris_rx": None,
    }
    try:
        with open(json_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        ann = data.get("Annotations", data)
        pose = ann.get("pose", {})
        head = pose.get("head", [])

        if isinstance(head, list) and len(head) >= 2:
            result["yaw"] = safe_float(head[0])
            result["pitch"] = safe_float(head[1])
            if len(head) >= 3:
                result["roll"] = safe_float(head[2])

        result["gaze_point"] = pose.get("point")

        for anno in ann.get("annotations", []):
            label = str(anno.get("label", "")).lower()
            points = anno.get("points", [])
            if label in ("l_center", "left_center") and points:
                pt = points[0]
                result["left_center"] = [safe_float(pt[0]), safe_float(pt[1])]
            elif label in ("r_center", "right_center") and points:
                pt = points[0]
                result["right_center"] = [safe_float(pt[0]), safe_float(pt[1])]
            elif label in ("l_iris", "left_iris"):
                result["left_iris_cx"] = safe_float(anno.get("cx"))
                result["left_iris_cy"] = safe_float(anno.get("cy"))
                result["left_iris_rx"] = safe_float(anno.get("rx"))
            elif label in ("r_iris", "right_iris"):
                result["right_iris_cx"] = safe_float(anno.get("cx"))
                result["right_iris_cy"] = safe_float(anno.get("cy"))
                result["right_iris_rx"] = safe_float(anno.get("rx"))
    except Exception as e:
        result["error"] = str(e)
    return result


# ============================================================
# Dataset 2: 안구 움직임 CVAT XML 파서
# ============================================================

def parse_points(s: str) -> List[List[float]]:
    if not s:
        return []
    try:
        return [[float(v) for v in p.split(",")] for p in s.strip().split(";")]
    except Exception:
        return []


def iris_stats(points: List[List[float]]) -> Tuple[float, float, float]:
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    cx = float(np.mean(xs))
    cy = float(np.mean(ys))
    rx = float((max(xs) - min(xs) + max(ys) - min(ys)) / 4)
    return cx, cy, max(rx, 1.0)


def parse_eye_xml(xml_path: str) -> List[Dict[str, Any]]:
    frames = []
    try:
        tree = ET.parse(xml_path)
        root = tree.getroot()
    except Exception as e:
        return [{"error": str(e), "path": xml_path}]

    for img_elem in root.findall("image"):
        frame = {
            "source": "eye_xml", "path": xml_path,
            "image_name": img_elem.get("name"),
            "width": int(img_elem.get("width", 1280)),
            "height": int(img_elem.get("height", 720)),
            "right_center": None, "left_center": None,
            "right_iris_cx": None, "right_iris_cy": None, "right_iris_rx": None,
            "left_iris_cx": None, "left_iris_cy": None, "left_iris_rx": None,
        }
        for elem in img_elem:
            label = str(elem.get("label", "")).lower()
            pts = parse_points(elem.get("points", ""))
            if label == "right_center" and pts:
                frame["right_center"] = pts[0]
            elif label == "left_center" and pts:
                frame["left_center"] = pts[0]
            elif label == "right_pupil" and pts and frame["right_center"] is None:
                xs = [p[0] for p in pts]
                ys = [p[1] for p in pts]
                frame["right_center"] = [float(np.mean(xs)), float(np.mean(ys))]
            elif label == "left_pupil" and pts and frame["left_center"] is None:
                xs = [p[0] for p in pts]
                ys = [p[1] for p in pts]
                frame["left_center"] = [float(np.mean(xs)), float(np.mean(ys))]
            elif label == "right_iris" and pts:
                cx, cy, rx = iris_stats(pts)
                frame["right_iris_cx"] = cx
                frame["right_iris_cy"] = cy
                frame["right_iris_rx"] = rx
            elif label == "left_iris" and pts:
                cx, cy, rx = iris_stats(pts)
                frame["left_iris_cx"] = cx
                frame["left_iris_cy"] = cy
                frame["left_iris_rx"] = rx
        frames.append(frame)
    return frames


# ============================================================
# 라벨 → 방향 변환
# ============================================================

def gaze_from_headpose(yaw, pitch) -> str:
    if yaw is None or pitch is None:
        return "UNKNOWN"
    try:
        yaw = float(yaw)
        pitch = float(pitch)
    except Exception:
        return "UNKNOWN"
    if abs(yaw) <= YAW_THRESHOLD and abs(pitch) <= PITCH_THRESHOLD:
        return "CENTER"
    if abs(yaw) >= abs(pitch):
        return "RIGHT" if yaw > 0 else "LEFT"
    return "DOWN" if pitch > 0 else "UP"


def gaze_from_iris_offset(pupil, iris_cx, iris_cy, iris_rx) -> str:
    if pupil is None or iris_cx is None or iris_cy is None or iris_rx is None:
        return "UNKNOWN"
    if iris_rx < 1:
        return "UNKNOWN"
    try:
        dx = (float(pupil[0]) - float(iris_cx)) / float(iris_rx)
        dy = (float(pupil[1]) - float(iris_cy)) / float(iris_rx)
    except Exception:
        return "UNKNOWN"
    if abs(dx) <= IRIS_OFFSET_THRESH and abs(dy) <= IRIS_OFFSET_THRESH:
        return "CENTER"
    if abs(dx) >= abs(dy):
        return "RIGHT" if dx > 0 else "LEFT"
    return "DOWN" if dy > 0 else "UP"


def assign_gaze_label(d: Dict[str, Any]) -> str:
    label = gaze_from_headpose(d.get("yaw"), d.get("pitch"))
    if label != "UNKNOWN":
        return label
    for side in ("right", "left"):
        pupil = d.get(f"{side}_center")
        cx = d.get(f"{side}_iris_cx")
        cy = d.get(f"{side}_iris_cy")
        rx = d.get(f"{side}_iris_rx")
        label = gaze_from_iris_offset(pupil, cx, cy, rx)
        if label != "UNKNOWN":
            return label
    return "UNKNOWN"


# ============================================================
# MediaPipe 특징 추출
# ============================================================

class FaceFeatureExtractor:
    FEATURE_DIM = 8

    def __init__(self, static_mode: bool = True):
        self.mesh = mp.solutions.face_mesh.FaceMesh(
            static_image_mode=static_mode,
            max_num_faces=1,
            refine_landmarks=True,
            min_detection_confidence=0.4,
            min_tracking_confidence=0.4,
        )

    def extract(self, frame_bgr: np.ndarray) -> Optional[np.ndarray]:
        try:
            h, w = frame_bgr.shape[:2]
            rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
            result = self.mesh.process(rgb)
            if not result.multi_face_landmarks:
                return None

            lm = result.multi_face_landmarks[0].landmark

            def pt(idx: int) -> np.ndarray:
                return np.array([lm[idx].x * w, lm[idx].y * h], dtype=np.float32)

            grp_a = np.mean([pt(i) for i in IRIS_GROUP_A], axis=0)
            grp_b = np.mean([pt(i) for i in IRIS_GROUP_B], axis=0)
            if grp_a[0] < grp_b[0]:
                left_iris, right_iris = grp_a, grp_b
            else:
                left_iris, right_iris = grp_b, grp_a

            left_mid = (pt(EYE_OUTER_LEFT) + pt(EYE_INNER_LEFT)) / 2
            right_mid = (pt(EYE_INNER_RIGHT) + pt(EYE_OUTER_RIGHT)) / 2
            left_w = np.linalg.norm(pt(EYE_INNER_LEFT) - pt(EYE_OUTER_LEFT))
            right_w = np.linalg.norm(pt(EYE_OUTER_RIGHT) - pt(EYE_INNER_RIGHT))
            if left_w < 1 or right_w < 1:
                return None

            left_offset = (left_iris - left_mid) / left_w
            right_offset = (right_iris - right_mid) / right_w

            nose = pt(NOSE_TIP)
            ear_l = pt(EAR_LEFT)
            ear_r = pt(EAR_RIGHT)
            chin = pt(CHIN)
            face_center = (ear_l + ear_r) / 2
            face_width = float(np.linalg.norm(ear_r - ear_l)) + 1e-6
            face_height = float(np.linalg.norm(chin - face_center)) + 1e-6
            head_x = float((nose[0] - face_center[0]) / face_width)
            head_y = float((nose[1] - face_center[1]) / face_height)
            avg_x = float((left_offset[0] + right_offset[0]) / 2)
            avg_y = float((left_offset[1] + right_offset[1]) / 2)

            return np.array([
                float(left_offset[0]), float(left_offset[1]),
                float(right_offset[0]), float(right_offset[1]),
                head_x, head_y, avg_x, avg_y,
            ], dtype=np.float32)
        except Exception:
            return None

    def close(self):
        self.mesh.close()


# ============================================================
# 이미지 매칭
# ============================================================

def build_image_index(image_root: str) -> Dict[str, str]:
    root = Path(image_root)
    image_index = {}
    if not root.exists():
        return image_index
    for ext in ["*.jpg", "*.jpeg", "*.png", "*.bmp"]:
        for p in root.rglob(ext):
            image_index[p.stem] = str(p)
    return image_index


def find_eye_rgb_dir(xml_path: str, image_root: str) -> Optional[Path]:
    parts = Path(xml_path).parts
    for i, p in enumerate(parts):
        if re.match(r"^\d{3}$", p) and i + 1 < len(parts):
            subject = p
            condition = parts[i + 1]
            candidates = [
                Path(image_root) / "TS_G1_1" / subject / condition / "RGB",
                Path(image_root) / subject / condition / "RGB",
                Path(image_root) / "U" / subject / condition / "RGB",
            ]
            for c in candidates:
                if c.exists():
                    return c
    return None


# ============================================================
# 데이터셋 로딩 + 특징 추출
# ============================================================

def load_display_samples(extractor: FaceFeatureExtractor) -> List[Tuple[np.ndarray, str]]:
    print("\n[1] 디스플레이 중심 안구 움직임 JSON 데이터 로딩")
    label_dir = DISPLAY_GAZE_LABEL_PATH
    if not os.path.exists(label_dir):
        if os.path.exists(DISPLAY_GAZE_LABEL_PATH_FALLBACK):
            print(f"  [경로] {label_dir} 없음 → fallback: {DISPLAY_GAZE_LABEL_PATH_FALLBACK}")
            label_dir = DISPLAY_GAZE_LABEL_PATH_FALLBACK
        else:
            print(f"  [경고] JSON 라벨 경로를 찾을 수 없습니다: {label_dir}")
            return []

    json_files = sorted(Path(label_dir).rglob("*.json"))
    print(f"발견된 JSON: {len(json_files)}개")

    print("이미지 인덱스 생성 중...")
    image_index = build_image_index(DISPLAY_GAZE_IMAGE_PATH)
    print(f"인덱싱된 이미지: {len(image_index)}개")

    samples = []
    missed = 0
    for jf in tqdm(json_files[:MAX_DISPLAY_JSON], desc="display json"):
        d = parse_display_json(str(jf))
        if "error" in d:
            continue
        label = assign_gaze_label(d)
        if label == "UNKNOWN":
            continue
        img_path = image_index.get(jf.stem)
        if img_path is None:
            missed += 1
            continue
        img = imread_unicode(img_path)
        if img is None:
            continue
        feat = extractor.extract(img)
        if feat is None:
            continue
        samples.append((feat, label))

    print(f"디스플레이 데이터 유효 샘플: {len(samples)}개")
    print(f"이미지 매칭 실패: {missed}개")
    print(f"라벨 분포: {dict(Counter([l for _, l in samples]))}")
    return samples


def load_eye_samples(extractor: FaceFeatureExtractor) -> List[Tuple[np.ndarray, str]]:
    print("\n[2] 안구 움직임 XML 데이터 로딩")
    if not os.path.exists(EYE_MOVEMENT_LABEL_PATH):
        print(f"  [경고] {EYE_MOVEMENT_LABEL_PATH} 없음 → 건너뜀")
        return []
    xml_files = sorted(Path(EYE_MOVEMENT_LABEL_PATH).rglob("*_RGB.xml"))
    print(f"발견된 RGB XML: {len(xml_files)}개")

    samples = []
    for xf in tqdm(xml_files[:MAX_EYE_XML], desc="eye xml"):
        rgb_dir = find_eye_rgb_dir(str(xf), EYE_MOVEMENT_IMAGE_PATH)
        frames = parse_eye_xml(str(xf))
        if rgb_dir is None or not frames:
            continue
        step = max(1, len(frames) // MAX_FRAMES_PER_XML)
        selected = frames[::step][:MAX_FRAMES_PER_XML]
        for frame_info in selected:
            if "error" in frame_info:
                continue
            label = assign_gaze_label(frame_info)
            if label == "UNKNOWN":
                continue
            image_name = frame_info.get("image_name")
            if not image_name:
                continue
            img_path = rgb_dir / image_name
            if not img_path.exists():
                continue
            img = imread_unicode(str(img_path))
            if img is None:
                continue
            feat = extractor.extract(img)
            if feat is None:
                continue
            samples.append((feat, label))

    print(f"안구 움직임 데이터 유효 샘플: {len(samples)}개")
    print(f"라벨 분포: {dict(Counter([l for _, l in samples]))}")
    return samples


# ============================================================
# CSV 기반 학습 데이터 로딩 (feature_extract.py 출력 사용)
# ============================================================

def load_samples_from_json_rgb_csv() -> List[Tuple[np.ndarray, str]]:
    """features_json_rgb.csv에서 학습 샘플 로딩."""
    samples = []
    if not os.path.exists(JSON_RGB_CSV):
        print(f"  [경고] {JSON_RGB_CSV} 없음 → 건너뜀")
        return samples

    def _iris_offset(row, cx_k, cy_k, rx_k, ry_k, px_k, py_k):
        cx = safe_float(row.get(cx_k, ""))
        cy = safe_float(row.get(cy_k, ""))
        rx = safe_float(row.get(rx_k, ""))
        ry = safe_float(row.get(ry_k, ""))
        px = safe_float(row.get(px_k, ""))
        py = safe_float(row.get(py_k, ""))
        if None in (cx, cy, rx, ry, px, py) or rx < 1 or ry < 1:
            return 0.0, 0.0
        return (px - cx) / rx, (py - cy) / ry

    with open(JSON_RGB_CSV, encoding="utf-8") as f:
        for row in csv.DictReader(f):
            try:
                head_x = safe_float(row.get("head_yaw", ""))
                head_y = safe_float(row.get("head_pitch", ""))
                if head_x is None or head_y is None:
                    continue

                r_ox, r_oy = _iris_offset(row,
                    "r_iris_cx", "r_iris_cy", "r_iris_rx", "r_iris_ry",
                    "r_pupil_cx", "r_pupil_cy")
                l_ox, l_oy = _iris_offset(row,
                    "l_iris_cx", "l_iris_cy", "l_iris_rx", "l_iris_ry",
                    "l_pupil_cx", "l_pupil_cy")
                avg_x = (l_ox + r_ox) / 2
                avg_y = (l_oy + r_oy) / 2

                feat = np.array(
                    [l_ox, l_oy, r_ox, r_oy, head_x, head_y, avg_x, avg_y],
                    dtype=np.float32,
                )
                label = gaze_from_headpose(head_x, head_y)
                if label == "UNKNOWN":
                    continue
                samples.append((feat, label))
            except Exception:
                continue

    print(f"\n[CSV-1] json_rgb CSV 유효 샘플: {len(samples)}개")
    if samples:
        print(f"  라벨 분포: {dict(Counter([l for _, l in samples]))}")
    return samples


def load_samples_from_mpiifacegaze_csv() -> List[Tuple[np.ndarray, str]]:
    """features_mpiifacegaze.csv에서 학습 샘플 로딩.
    head_ry=yaw(좌우), head_rx=pitch(상하), gaze_x/y는 카메라 좌표계 타겟이므로
    head pose를 기반으로 iris offset을 근사한다.
    """
    samples = []
    if not os.path.exists(MPIIFACEGAZE_CSV):
        print(f"  [경고] {MPIIFACEGAZE_CSV} 없음 → 건너뜀")
        return samples

    with open(MPIIFACEGAZE_CSV, encoding="utf-8") as f:
        for row in csv.DictReader(f):
            try:
                head_ry = safe_float(row.get("head_ry", ""))  # yaw  (좌우)
                head_rx = safe_float(row.get("head_rx", ""))  # pitch (상하)
                if head_ry is None or head_rx is None:
                    continue

                # head pose 기반 iris offset 근사 (눈은 머리 회전의 약 50% 따라감)
                iris_ox = float(head_ry) * 0.5
                iris_oy = float(head_rx) * 0.5

                feat = np.array(
                    [iris_ox, iris_oy, iris_ox, iris_oy,
                     float(head_ry), float(head_rx),
                     iris_ox, iris_oy],
                    dtype=np.float32,
                )
                label = gaze_from_headpose(head_ry, head_rx)
                if label == "UNKNOWN":
                    continue
                samples.append((feat, label))
            except Exception:
                continue

    print(f"\n[CSV-2] MPIIFaceGaze CSV 유효 샘플: {len(samples)}개")
    if samples:
        print(f"  라벨 분포: {dict(Counter([l for _, l in samples]))}")
    return samples


# ============================================================
# UP/DOWN 데이터 증강
# ============================================================

def augment_vertical_samples(samples: List[Tuple[np.ndarray, str]], seed: int = 42) -> List[Tuple[np.ndarray, str]]:
    centers = [f for f, l in samples if l == "CENTER"]
    if len(centers) < 5:
        print(f"[증강] CENTER 샘플 부족({len(centers)}개) → 증강 생략")
        return samples

    rng = np.random.RandomState(seed)
    augmented = list(samples)

    for _ in range(AUGMENT_DOWN_N):
        nf = centers[rng.randint(len(centers))].copy()
        eye_shift = rng.uniform(0.035, 0.12)
        head_shift = rng.uniform(0.04, 0.14)
        noise = rng.normal(0, 0.004, nf.shape).astype(np.float32)
        nf[1] += eye_shift
        nf[3] += eye_shift
        nf[5] += head_shift
        nf[7] += eye_shift
        nf += noise
        augmented.append((nf, "DOWN"))

    for _ in range(AUGMENT_UP_N):
        nf = centers[rng.randint(len(centers))].copy()
        eye_shift = rng.uniform(0.030, 0.10)
        head_shift = rng.uniform(0.035, 0.12)
        noise = rng.normal(0, 0.004, nf.shape).astype(np.float32)
        nf[1] -= eye_shift
        nf[3] -= eye_shift
        nf[5] -= head_shift
        nf[7] -= eye_shift
        nf += noise
        augmented.append((nf, "UP"))

    print(f"[증강] DOWN {AUGMENT_DOWN_N}개, UP {AUGMENT_UP_N}개 synthetic 생성")
    return augmented


# ============================================================
# 모델 학습
# ============================================================

def train_or_load_model():
    if FORCE_RETRAIN:
        for p in (MODEL_PATH, LABEL_ENCODER_PATH):
            if os.path.exists(p):
                os.remove(p)

    if SKLEARN_AVAILABLE and os.path.exists(MODEL_PATH) and os.path.exists(LABEL_ENCODER_PATH):
        print("\n[모델] 저장된 모델 발견. 기존 모델을 불러옵니다.")
        clf = joblib.load(MODEL_PATH)
        le = joblib.load(LABEL_ENCODER_PATH)
        print("불러온 클래스:", list(le.classes_))
        return clf, le

    if not SKLEARN_AVAILABLE:
        print("\n[모델] scikit-learn 없음. rule-based만 사용합니다.")
        return None, None

    extractor = FaceFeatureExtractor(static_mode=True)
    all_samples = []
    all_samples.extend(load_display_samples(extractor))
    all_samples.extend(load_eye_samples(extractor))
    extractor.close()

    # feature_extract.py 출력 CSV에서 추가 학습 데이터 로딩
    print("\n[CSV] feature_extract.py 출력 CSV 로딩")
    all_samples.extend(load_samples_from_json_rgb_csv())
    all_samples.extend(load_samples_from_mpiifacegaze_csv())

    print("\n[3] 원본 학습 샘플 통계")
    print(f"원본 유효 샘플: {len(all_samples)}개")
    print(f"원본 라벨 분포: {dict(Counter([l for _, l in all_samples]))}")

    all_samples = augment_vertical_samples(all_samples)

    print("\n[4] 전체 학습 샘플 통계")
    print(f"전체 유효 샘플: {len(all_samples)}개")
    print(f"전체 라벨 분포: {dict(Counter([l for _, l in all_samples]))}")

    if len(all_samples) < 30:
        print("학습 샘플이 너무 적습니다. rule-based 방식으로 실행합니다.")
        return None, None

    X = np.array([f for f, _ in all_samples], dtype=np.float32)
    y_labels = [l for _, l in all_samples]

    if len(set(y_labels)) < 2:
        print("라벨 클래스가 2개 미만입니다. rule-based 방식으로 실행합니다.")
        return None, None

    le = LabelEncoder()
    y = le.fit_transform(y_labels)
    counts = Counter(y)
    stratify = y if min(counts.values()) >= 2 else None

    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.2, random_state=42, stratify=stratify
    )

    clf = RandomForestClassifier(
        n_estimators=250,
        random_state=42,
        n_jobs=-1,
        class_weight="balanced",
        max_depth=12,
    )

    print("\n[5] RandomForest 시선 분류 모델 학습 중...")
    clf.fit(X_train, y_train)
    pred = clf.predict(X_test)
    acc = accuracy_score(y_test, pred)

    print(f"검증 정확도: {acc:.3f}")
    print("클래스:", list(le.classes_))

    try:
        print(classification_report(
            y_test, pred,
            labels=list(range(len(le.classes_))),
            target_names=list(le.classes_),
            zero_division=0,
        ))
    except Exception as e:
        print(f"[분류 리포트 생략] {e}")

    joblib.dump(clf, MODEL_PATH)
    joblib.dump(le, LABEL_ENCODER_PATH)
    print(f"모델 저장: {MODEL_PATH}")
    print(f"라벨 인코더 저장: {LABEL_ENCODER_PATH}")
    return clf, le


# ============================================================
# 캘리브레이션 기반 실시간 분류기
# ============================================================

class CalibratedGazeClassifier:
    def __init__(self, clf=None, le=None):
        self.clf = clf
        self.le = le
        self.calibration_features = []
        self.baseline = None
        self.recent = deque(maxlen=SMOOTHING_WINDOW)
        self.last_debug = {
            "d_head_x": 0.0, "d_head_y": 0.0,
            "d_avg_x": 0.0, "d_avg_y": 0.0,
            "calibrated": False, "raw": "CENTER",
        }

    def _build_baseline(self):
        arr = np.array(self.calibration_features, dtype=np.float32)
        self.baseline = np.median(arr, axis=0)

    def _smooth(self, pred: str) -> str:
        self.recent.append(pred)
        counts = Counter(self.recent)
        return counts.most_common(1)[0][0]

    def predict_raw(self, features: Optional[np.ndarray]) -> str:
        if features is None:
            self.last_debug["calibrated"] = self.baseline is not None
            self.last_debug["raw"] = "NO_FACE"
            return "NO_FACE"

        if self.baseline is None:
            self.calibration_features.append(features.copy())
            if len(self.calibration_features) >= CALIBRATION_FRAMES:
                self._build_baseline()
            self.last_debug["calibrated"] = False
            self.last_debug["raw"] = "CENTER"
            return "CENTER"

        head_x = float(features[4])
        head_y = float(features[5])
        avg_x = float(features[6])
        avg_y = float(features[7])

        base_head_x = float(self.baseline[4])
        base_head_y = float(self.baseline[5])
        base_avg_x = float(self.baseline[6])
        base_avg_y = float(self.baseline[7])

        d_head_x = head_x - base_head_x
        d_head_y = head_y - base_head_y
        d_avg_x = avg_x - base_avg_x
        d_avg_y = avg_y - base_avg_y

        self.last_debug = {
            "d_head_x": d_head_x, "d_head_y": d_head_y,
            "d_avg_x": d_avg_x, "d_avg_y": d_avg_y,
            "calibrated": True, "raw": "CENTER",
        }

        # 각 방향 신호를 임계값으로 정규화해서 가장 강한 방향 선택
        down_sig = max(d_head_y / DOWN_HEAD_DELTA, d_avg_y / DOWN_EYE_DELTA, 0.0)
        up_sig   = max(-d_head_y / DOWN_HEAD_DELTA, -d_avg_y / DOWN_EYE_DELTA, 0.0)
        h_sig    = max(abs(d_head_x) / SIDE_HEAD_DELTA, abs(d_avg_x) / SIDE_EYE_DELTA, 0.0)

        best_sig = max(down_sig, up_sig, h_sig)

        if best_sig >= 1.0:
            if best_sig == down_sig:
                self.last_debug["raw"] = "DOWN"
                return "DOWN"
            elif best_sig == up_sig:
                self.last_debug["raw"] = "UP"
                return "UP"
            else:
                pred = "RIGHT" if d_head_x > 0 else "LEFT"
                self.last_debug["raw"] = pred
                return pred

        # 3. 애매한 경우 모델 참고. 단, 모델이 방향을 과하게 내면 CENTER로 보정.
        if self.clf is not None and self.le is not None:
            try:
                pred = self.clf.predict([features])[0]
                model_result = self.le.inverse_transform([pred])[0]
                if model_result in ("UP", "DOWN", "LEFT", "RIGHT"):
                    self.last_debug["raw"] = "CENTER"
                    return "CENTER"
                self.last_debug["raw"] = model_result
                return model_result
            except Exception:
                pass

        self.last_debug["raw"] = "CENTER"
        return "CENTER"

    def predict(self, features: Optional[np.ndarray]) -> str:
        raw = self.predict_raw(features)
        return self._smooth(raw)

    def debug_text(self) -> str:
        if not self.last_debug["calibrated"]:
            return f"Calibrating... {len(self.calibration_features)}/{CALIBRATION_FRAMES} | Look CENTER"
        return (
            f"raw:{self.last_debug['raw']} "
            f"dHY:{self.last_debug['d_head_y']:.3f} "
            f"dEY:{self.last_debug['d_avg_y']:.3f} "
            f"dHX:{self.last_debug['d_head_x']:.3f} "
            f"dEX:{self.last_debug['d_avg_x']:.3f}"
        )


# ============================================================
# 실시간 상태/피드백
# ============================================================

@dataclass
class GazeState:
    total_frames: int = 0
    center_count: int = 0
    left_count: int = 0
    right_count: int = 0
    up_count: int = 0
    down_count: int = 0
    no_face_count: int = 0
    current_gaze: str = "NO_FACE"
    started_at: float = field(default_factory=time.time)
    non_center_since: Optional[float] = None  # 비중심 응시 시작 시각

    def update(self, gaze: str):
        self.total_frames += 1
        self.current_gaze = gaze
        if gaze == "CENTER":
            self.non_center_since = None   # 정면 복귀 시 타이머 리셋
            self.center_count += 1
        else:
            if self.non_center_since is None:
                self.non_center_since = time.time()
            if gaze == "LEFT":
                self.left_count += 1
            elif gaze == "RIGHT":
                self.right_count += 1
            elif gaze == "UP":
                self.up_count += 1
            elif gaze == "DOWN":
                self.down_count += 1
            else:
                self.no_face_count += 1

    def snapshot(self) -> Dict:
        total = max(self.total_frames, 1)
        side_count = self.left_count + self.right_count
        non_center_duration = (
            round(time.time() - self.non_center_since, 1)
            if self.non_center_since is not None else 0.0
        )
        return {
            "elapsed_seconds": round(time.time() - self.started_at, 1),
            "total_frames": self.total_frames,
            "current_gaze": self.current_gaze,
            "non_center_duration": non_center_duration,
            "center_ratio": self.center_count / total,
            "left_ratio": self.left_count / total,
            "right_ratio": self.right_count / total,
            "side_ratio": side_count / total,
            "up_ratio": self.up_count / total,
            "down_ratio": self.down_count / total,
            "no_face_ratio": self.no_face_count / total,
        }


def make_feedback(state: Dict) -> str:
    gaze = state["current_gaze"]
    duration = state.get("non_center_duration", 0.0)

    if gaze == "CENTER":
        return "정면을 잘 응시하고 있습니다."

    if duration < 2.0:
        return ""  # 2초 미만은 경고 없음

    if gaze == "DOWN":
        return "아래를 보고 있습니다. 카메라를 응시하세요."
    if gaze == "UP":
        return "위를 보고 있습니다. 카메라를 응시하세요."
    if gaze == "LEFT":
        return "왼쪽을 보고 있습니다. 정면을 응시하세요."
    if gaze == "RIGHT":
        return "오른쪽을 보고 있습니다. 정면을 응시하세요."
    if gaze == "NO_FACE":
        return "얼굴이 감지되지 않습니다. 카메라 앞으로 이동하세요."
    return "정면을 응시하세요."


def draw_overlay(frame: np.ndarray, state: Dict, model_mode: str, debug_text: str) -> np.ndarray:
    img = frame.copy()
    gaze = state["current_gaze"]
    center = state["center_ratio"] * 100
    down = state["down_ratio"] * 100
    up = state["up_ratio"] * 100
    side = state["side_ratio"] * 100
    no_face = state["no_face_ratio"] * 100
    elapsed = state["elapsed_seconds"]
    feedback = make_feedback(state)

    if gaze == "CENTER":
        color = (0, 200, 0)
    elif gaze == "NO_FACE":
        color = (0, 0, 255)
    elif gaze in ("UP", "DOWN"):
        color = (255, 180, 0)
    else:
        color = (0, 165, 255)

    cv2.rectangle(img, (10, 10), (630, 265), (0, 0, 0), -1)
    cv2.rectangle(img, (10, 10), (630, 265), color, 2)

    cv2.putText(img, f"Gaze: {gaze}", (25, 45), cv2.FONT_HERSHEY_SIMPLEX, 0.85, color, 2)
    cv2.putText(img, f"Mode: {model_mode}", (25, 78), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (200, 200, 200), 2)
    cv2.putText(
        img,
        f"Center:{center:.1f}% | Down:{down:.1f}% | Up:{up:.1f}% | Side:{side:.1f}% | NoFace:{no_face:.1f}%",
        (25, 110), cv2.FONT_HERSHEY_SIMPLEX, 0.50, (255, 255, 255), 2,
    )
    duration = state.get("non_center_duration", 0.0)
    dur_text = f" | 비중심 {duration:.1f}s" if duration > 0 else ""
    cv2.putText(img, f"Time:{elapsed:.1f}s | Frames:{state['total_frames']}{dur_text}",
                (25, 143), cv2.FONT_HERSHEY_SIMPLEX, 0.50, (255, 255, 255), 2)
    fb_color = (0, 255, 0) if gaze == "CENTER" else (0, 255, 255) if duration < 2.0 else (0, 100, 255)
    cv2.putText(img, f"Feedback: {feedback}",
                (25, 176), cv2.FONT_HERSHEY_SIMPLEX, 0.58, fb_color, 2)
    cv2.putText(img, debug_text,
                (25, 210), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (180, 180, 180), 1)
    cv2.putText(img, "Start: look CENTER for 2 sec | Press Q to quit",
                (25, 242), cv2.FONT_HERSHEY_SIMPLEX, 0.48, (200, 200, 200), 1)
    return img


# ============================================================
# 웹캠 실시간 분석
# ============================================================

def run_camera(clf, le):
    model_mode = "Trained RF + Calibrated Vertical Rules" if clf is not None and le is not None else "Calibrated Rule-based"

    print("\n[6] 웹캠 실시간 분석 시작")
    print(f"사용 모드: {model_mode}")
    print("중요: 시작 후 1.5~2초 동안은 카메라를 정면으로 보고 있어야 합니다.")
    print("종료하려면 카메라 창에서 q 키를 누르세요.")

    cap = cv2.VideoCapture(CAMERA_INDEX, cv2.CAP_DSHOW)
    if not cap.isOpened():
        print("웹캠을 열 수 없습니다. CAMERA_INDEX를 0에서 1 또는 2로 바꿔보세요.")
        return

    cap.set(cv2.CAP_PROP_FRAME_WIDTH, FRAME_WIDTH)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, FRAME_HEIGHT)

    extractor = FaceFeatureExtractor(static_mode=False)
    state = GazeState()
    gaze_classifier = CalibratedGazeClassifier(clf, le)

    while True:
        ret, frame = cap.read()
        if not ret:
            print("프레임을 읽지 못했습니다.")
            break

        frame = cv2.flip(frame, 1)
        frame = cv2.resize(frame, (FRAME_WIDTH, FRAME_HEIGHT))
        features = extractor.extract(frame)
        gaze = gaze_classifier.predict(features)
        state.update(gaze)

        debug_text = gaze_classifier.debug_text()
        output = draw_overlay(frame, state.snapshot(), model_mode, debug_text)
        cv2.imshow("AI Interview/Presentation Gaze Feedback", output)

        key = cv2.waitKey(1) & 0xFF
        if key == ord("q"):
            break

    cap.release()
    extractor.close()
    cv2.destroyAllWindows()

    final = state.snapshot()
    print("\n최종 결과")
    print("-" * 40)
    print(f"분석 시간: {final['elapsed_seconds']}초")
    print(f"전체 프레임: {final['total_frames']}")
    print(f"정면 응시 비율: {final['center_ratio'] * 100:.1f}%")
    print(f"아래 시선 비율: {final['down_ratio'] * 100:.1f}%")
    print(f"위 시선 비율: {final['up_ratio'] * 100:.1f}%")
    print(f"좌우 이탈 비율: {final['side_ratio'] * 100:.1f}%")
    print(f"얼굴 미검출 비율: {final['no_face_ratio'] * 100:.1f}%")
    print(f"마지막 피드백: {make_feedback(final)}")


def main():
    print("=" * 70)
    print("AI 발표/면접 시선 분석: AI Hub 학습 + 실시간 웹캠 v3")
    print("=" * 70)
    print("\n경로 확인")
    print("DISPLAY_GAZE_LABEL_PATH:", DISPLAY_GAZE_LABEL_PATH, os.path.exists(DISPLAY_GAZE_LABEL_PATH))
    print("DISPLAY_GAZE_IMAGE_PATH:", DISPLAY_GAZE_IMAGE_PATH, os.path.exists(DISPLAY_GAZE_IMAGE_PATH))
    print("EYE_MOVEMENT_LABEL_PATH:", EYE_MOVEMENT_LABEL_PATH, os.path.exists(EYE_MOVEMENT_LABEL_PATH))
    print("EYE_MOVEMENT_IMAGE_PATH:", EYE_MOVEMENT_IMAGE_PATH, os.path.exists(EYE_MOVEMENT_IMAGE_PATH))

    clf, le = train_or_load_model()
    run_camera(clf, le)


if __name__ == "__main__":
    main()
