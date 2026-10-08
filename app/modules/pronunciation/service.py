import re
from typing import Any


def _normalize(text: str) -> str:
    return re.sub(r"[^0-9A-Za-z가-힣]", "", text).lower()


def _edit_distance(left: str, right: str) -> tuple[int, list[dict[str, Any]]]:
    rows = len(left) + 1
    cols = len(right) + 1
    matrix = [[0] * cols for _ in range(rows)]
    for row in range(rows):
        matrix[row][0] = row
    for col in range(cols):
        matrix[0][col] = col
    for row in range(1, rows):
        for col in range(1, cols):
            cost = 0 if left[row - 1] == right[col - 1] else 1
            matrix[row][col] = min(
                matrix[row - 1][col] + 1,
                matrix[row][col - 1] + 1,
                matrix[row - 1][col - 1] + cost,
            )
    # A compact substitution list is enough for actionable MVP feedback.
    difficult = [
        {"expected": expected, "recognized": recognized, "position": index}
        for index, (expected, recognized) in enumerate(zip(left, right, strict=False))
        if expected != recognized
    ][:5]
    return matrix[-1][-1], difficult


def estimate_pronunciation_clarity(
    expected: str, recognized: str, stt_confidence: float | None = None
) -> dict[str, Any]:
    expected_normalized = _normalize(expected)
    recognized_normalized = _normalize(recognized)
    confidence = None if stt_confidence is None else max(0.0, min(stt_confidence, 1.0))
    if (
        len(expected_normalized) < 4
        or len(recognized_normalized) < 2
        or (confidence is not None and confidence < 0.35)
    ):
        return {
            "status": "insufficient_signal",
            "pronunciation_clarity_score": None,
            "confidence": confidence,
            "method": "script_agreement",
            "expected": expected,
            "recognized": recognized,
            "difficult_units": [],
            "message": "대본 일치도를 비교하기에 인식된 내용이 충분하지 않습니다.",
        }
    distance, difficult = _edit_distance(expected_normalized, recognized_normalized)
    similarity = 1 - distance / max(len(expected_normalized), len(recognized_normalized), 1)
    score = max(0.0, similarity * 100)
    return {
        "status": "estimated",
        "pronunciation_clarity_score": round(score, 1),
        "confidence": confidence,
        "method": "script_agreement",
        "expected": expected,
        "recognized": recognized,
        "difficult_units": difficult,
        "message": (
            "대본과 인식 결과가 대체로 일치합니다."
            if score >= 80
            else "대본과 인식 결과가 다릅니다. 발음 정확도를 뜻하지는 않습니다."
        ),
    }


def estimate_stt_pronunciation_accuracy(
    recognized: str,
    *,
    reference_text: str | None = None,
    avg_logprob: float | None = None,
    no_speech_prob: float | None = None,
) -> dict[str, Any]:
    if reference_text is None:
        return {
            "status": "insufficient_signal",
            "pronunciation_clarity_score": None,
            "confidence": None,
            "expected": None,
            "recognized": recognized,
            "difficult_units": [],
            "method": "unavailable",
            "message": "확정된 대본 위치가 없어 대본 일치도를 비교할 수 없습니다.",
        }

    return estimate_pronunciation_clarity(reference_text, recognized)
