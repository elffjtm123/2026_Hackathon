import re
from typing import Any

from app.modules.script_sync.service import analyze_script

PRESETS: dict[str, dict[str, object]] = {
    "visionary_keynote": {
        "id": "visionary_keynote",
        "name": "비전 중심 키노트",
        "description": "핵심 아이디어를 짧고 명확하게 공개하는 전달 방식",
        "traits": ["간결함", "긴장과 해소", "핵심 문장"],
    },
    "dream_oratory": {
        "id": "dream_oratory",
        "name": "희망적 비전 연설",
        "description": "반복과 점층법으로 청중의 참여를 이끄는 전달 방식",
        "traits": ["반복", "점층법", "희망적 비전"],
    },
    "wartime_resolve": {
        "id": "wartime_resolve",
        "name": "단호한 결의",
        "description": "대비와 공동체 의지를 강조하는 단호한 전달 방식",
        "traits": ["단호한 문장", "대비", "공동체 의지"],
    },
    "high_intensity_rally": {
        "id": "high_intensity_rally",
        "name": "고강도 호소",
        "description": "이념이나 인물 모방 없이 반복과 감정 강도만 추상화한 방식",
        "traits": ["반복", "감정 강도", "행동 촉구"],
    },
}

UNSAFE_PATTERNS = (
    re.compile(r"(죽여|말살|폭력을\s*선동|테러를\s*찬양)"),
    re.compile(r"(인종|민족|종교).{0,12}(열등|제거|추방)"),
)


def normalize_weights(vector: dict[str, float]) -> dict[str, float]:
    total = sum(vector.values())
    return {name: round(weight / total, 6) for name, weight in vector.items()}


def safety_check(script: str) -> dict[str, Any]:
    flags = (
        ["unsafe_incitement"] if any(pattern.search(script) for pattern in UNSAFE_PATTERNS) else []
    )
    return {"passed": not flags, "flags": flags}


class MockStyleTransferProvider:
    """Safe deterministic provider.

    Mock mode intentionally does not pretend to be an LLM. It preserves the source
    and returns an explicit preview warning while exercising the preview/apply flow.
    """

    async def transform(
        self,
        script: str,
        time_limit_seconds: int,
        style_vector: dict[str, float],
        intensity: float,
    ) -> dict[str, Any]:
        del style_vector, intensity
        safety = safety_check(script)
        plan = analyze_script(script, time_limit_seconds)
        return {
            "script": script,
            "estimated_duration_seconds": plan.estimated_duration_seconds,
            "change_summary": ["Mock provider는 원문을 변경하지 않습니다."],
            "warnings": ["개발용 Mock 결과입니다. 실제 스타일 변환에는 LLM provider가 필요합니다."],
            "safety": safety,
        }
