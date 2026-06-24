from fastapi.testclient import TestClient

from app.modules.pronunciation.service import estimate_pronunciation_clarity
from app.modules.script_sync.service import ScriptSyncService, analyze_script
from app.modules.style_transfer.service import normalize_weights, safety_check
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


def test_style_transfer_preview_and_apply(client: TestClient, auth: dict[str, object]) -> None:
    session = client.post(
        "/api/v1/sessions",
        headers=bearer(auth),
        json={
            "type": "presentation",
            "title": "스타일 테스트",
            "script": "저희 서비스는 발표 연습을 도와줍니다.",
            "time_limit_seconds": 60,
        },
    ).json()
    preview = client.post(
        "/api/v1/scripts/style-transfer",
        headers=bearer(auth),
        json={
            "script": session["active_script"],
            "time_limit_seconds": 60,
            "style_vector": {"visionary_keynote": 2, "dream_oratory": 1},
            "session_id": session["id"],
        },
    )
    assert preview.status_code == 201
    assert round(sum(preview.json()["style_vector"].values()), 5) == 1
    assert preview.json()["provider"] == "mock"
    applied = client.post(
        f"/api/v1/scripts/style-transfer/{preview.json()['job_id']}/apply",
        headers=bearer(auth),
    )
    assert applied.status_code == 200
    assert applied.json()["status"] == "applied"


def test_style_helpers() -> None:
    assert normalize_weights({"a": 2, "b": 1}) == {"a": 0.666667, "b": 0.333333}
    assert safety_check("특정 민족을 제거해야 한다")["passed"] is False


def test_unsafe_style_transfer_is_rejected(client: TestClient, auth: dict[str, object]) -> None:
    response = client.post(
        "/api/v1/scripts/style-transfer",
        headers=bearer(auth),
        json={
            "script": "특정 민족을 제거해야 한다는 폭력을 선동합니다.",
            "time_limit_seconds": 60,
            "style_vector": {"high_intensity_rally": 1},
        },
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "STYLE_SAFETY_REJECTED"


def test_presentation_features_can_be_disabled(client: TestClient, auth: dict[str, object]) -> None:
    session = client.post(
        "/api/v1/sessions",
        headers=bearer(auth),
        json={
            "type": "presentation",
            "title": "기능 비활성화 테스트",
            "script": "발표 기능을 선택해서 사용할 수 있습니다.",
            "time_limit_seconds": 60,
            "settings": {
                "karaoke_guide_enabled": False,
                "style_transfer_enabled": False,
            },
        },
    )
    assert session.status_code == 201
    assert session.json()["settings"]["karaoke_guide_enabled"] is False
    assert session.json()["settings"]["style_transfer_enabled"] is False

    preview = client.post(
        "/api/v1/scripts/style-transfer",
        headers=bearer(auth),
        json={
            "script": session.json()["active_script"],
            "time_limit_seconds": 60,
            "style_vector": {"visionary_keynote": 1},
            "session_id": session.json()["id"],
        },
    )
    assert preview.status_code == 409
    assert preview.json()["error"]["code"] == "FEATURE_DISABLED"
