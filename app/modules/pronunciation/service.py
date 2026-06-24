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
    confidence = 0.7 if stt_confidence is None else max(0.0, min(stt_confidence, 1.0))
    if len(expected_normalized) < 4 or len(recognized_normalized) < 2 or confidence < 0.35:
        return {
            "status": "insufficient_signal",
            "pronunciation_clarity_score": None,
            "confidence": round(confidence, 2),
            "expected": expected,
            "recognized": recognized,
            "difficult_units": [],
            "message": "발음 명료도를 추정하기에 신호가 충분하지 않습니다.",
        }
    distance, difficult = _edit_distance(expected_normalized, recognized_normalized)
    similarity = 1 - distance / max(len(expected_normalized), len(recognized_normalized), 1)
    score = max(0.0, similarity * 100)
    return {
        "status": "estimated",
        "pronunciation_clarity_score": round(score, 1),
        "confidence": round(confidence, 2),
        "expected": expected,
        "recognized": recognized,
        "difficult_units": difficult,
        "message": (
            "대본과 인식 결과가 대체로 일치합니다."
            if score >= 80
            else "표시된 음절을 조금 더 또렷하게 발음해보세요."
        ),
    }


def estimate_stt_pronunciation_accuracy(
    recognized: str,
    *,
    reference_text: str | None = None,
    avg_logprob: float | None = None,
    no_speech_prob: float | None = None,
) -> dict[str, Any]:
    from stt import ClarityAnalyzer

    stt_result = {
        "avg_logprob": -0.5 if avg_logprob is None else avg_logprob,
        "no_speech_prob": 0.1 if no_speech_prob is None else no_speech_prob,
    }
    result = ClarityAnalyzer().analyze(recognized, stt_result, reference_text)
    score = float(result["score"])
    return {
        "status": str(result["level"]).lower(),
        "pronunciation_clarity_score": round(score, 1),
        "confidence": round(max(0.0, min(1.0, score / 100)), 2),
        "expected": reference_text,
        "recognized": recognized,
        "difficult_units": [],
        "method": f"stt_{result['method']}",
        "message": result["feedback"],
    }
