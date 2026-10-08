from fastapi.testclient import TestClient

from app.modules.pronunciation.service import (
    estimate_pronunciation_clarity,
    estimate_stt_pronunciation_accuracy,
)
from app.modules.script_sync.service import ScriptSyncService, analyze_script
from tests.conftest import bearer


def test_korean_script_analysis_has_weighted_timeline() -> None:
    plan = analyze_script("안녕하세요, 오늘은 새 서비스를 소개합니다. 감사합니다!", 60)
    assert plan.syllable_count == 23
    assert plan.timeline[-1]["target_end_ms"] == 60_000
    assert plan.timeline[0]["target_end_ms"] > 0
    assert plan.target_syllables_per_minute == 23.0


def test_script_cursor_does_not_jump_backwards() -> None:
    plan = analyze_script("하나 둘 셋. 하나 둘 넷. 마지막 문장입니다.", 60)
    sync = ScriptSyncService(plan)
    first = sync.update("하나 둘 넷", 30_000, is_final=True)
    second = sync.update("하나 둘", 31_000, is_final=False)
    assert second["current_token_index"] >= first["current_token_index"]


def test_pronunciation_is_an_estimate_and_handles_weak_signal() -> None:
    result = estimate_pronunciation_clarity("혁신적인 사용자 경험", "혁신적인 사용자 경혐", 0.8)
    assert result["status"] == "estimated"
    assert 0 < result["pronunciation_clarity_score"] < 100
    weak = estimate_pronunciation_clarity("안녕", "안", 0.2)
    assert weak["status"] == "insufficient_signal"
    assert weak["pronunciation_clarity_score"] is None


def test_pronunciation_requires_reference_or_stt_confidence() -> None:
    result = estimate_stt_pronunciation_accuracy("안녕하세요")
    assert result["status"] == "insufficient_signal"
    assert result["pronunciation_clarity_score"] is None


def test_alignment_waits_for_relevant_final_text_and_normalizes_spacing() -> None:
    sync = ScriptSyncService(
        analyze_script("안녕하세요. 실시간 음성을 분석합니다. 감사합니다.", 60)
    )
    for text in ["", "네", "냉장고 바나나"]:
        result = sync.update(text, 40_000, is_final=True)
        assert result["alignment_status"] == "uncertain"
        assert result["current_token_index"] is None
        assert result["progress_ratio"] == 0
    partial = sync.update("실시간음성을분석합니다", 41_000, is_final=False)
    assert partial["current_token_index"] is None
    final = sync.update("실시간음성을분석합니다!", 42_000, is_final=True)
    assert final["alignment_status"] == "matched"
    assert (final["matched_start_token"], final["matched_end_token"]) == (1, 3)
    assert final["current_token_index"] == 3
    held = sync.update("냉장고 바나나", 43_000, is_final=True)
    assert held["current_token_index"] == 3
    assert held["alignment_status"] == "uncertain"


def test_repeated_script_is_ambiguous_and_does_not_advance() -> None:
    sync = ScriptSyncService(analyze_script("시스템을 소개합니다. 시스템을 소개합니다.", 60))
    result = sync.update("시스템을 소개합니다", 10_000, is_final=True)
    assert result["alignment_status"] == "uncertain"
    assert result["progress_ratio"] == 0


def test_stt_probabilities_are_not_pronunciation_accuracy() -> None:
    result = estimate_stt_pronunciation_accuracy(
        "안녕하세요", avg_logprob=-0.1, no_speech_prob=0.01
    )
    assert result["pronunciation_clarity_score"] is None
    match = estimate_stt_pronunciation_accuracy("안녕하세요", reference_text="안녕하세요.")
    assert match["method"] == "script_agreement"
    assert match["confidence"] is None
    assert match["pronunciation_clarity_score"] == 100


def test_script_api_and_session_fields(client: TestClient, auth: dict[str, object]) -> None:
    analyzed = client.post(
        "/api/v1/scripts/analyze",
        headers=bearer(auth),
        json={"script": "안녕하세요. 서비스 소개를 시작합니다.", "time_limit_seconds": 60},
    )
    assert analyzed.status_code == 200
    assert analyzed.json()["timeline"]

    created = client.post(
        "/api/v1/sessions",
        headers=bearer(auth),
        json={
            "type": "presentation",
            "title": "서비스 소개",
            "script": "안녕하세요. 서비스 소개를 시작합니다.",
            "time_limit_seconds": 60,
        },
    )
    assert created.status_code == 201
    assert created.json()["script_syllable_count"] > 0
    assert created.json()["active_script"] == "안녕하세요. 서비스 소개를 시작합니다."

    unrealistic = client.post(
        "/api/v1/sessions",
        headers=bearer(auth),
        json={
            "type": "presentation",
            "title": "너무 긴 대본",
            "script": "아주 빠르게 말해야 하는 긴 대본입니다. " * 300,
            "time_limit_seconds": 30,
        },
    )
    assert unrealistic.status_code == 422
    assert unrealistic.json()["error"]["code"] == "UNREALISTIC_TARGET_PACE"


def test_style_transfer_routes_are_removed(client: TestClient, auth: dict[str, object]) -> None:
    headers = bearer(auth)
    assert client.get("/api/v1/styles/presets", headers=headers).status_code == 404
    response = client.post("/api/v1/scripts/style-transfer", headers=headers, json={})
    assert response.status_code == 404
