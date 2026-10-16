import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.core.config import Settings
from app.main import create_app, create_local_gaze_adapter
from tests.fake_ai import FakeSpeechAdapter
from tests.test_session_flow import send_v2


def test_qwen_load_failure_is_unavailable_not_mock(
    monkeypatch: pytest.MonkeyPatch, tmp_path: object, fake_models: None
) -> None:
    def unavailable(*_args: object) -> None:
        raise RuntimeError("Qwen unavailable")

    monkeypatch.setattr("app.main.create_local_qwen_speech_adapter", unavailable)
    settings = Settings(
        app_env="development",
        database_url=f"sqlite+aiosqlite:///{tmp_path}/test.db",
        redis_url=None,
        vision_provider="uniface",
        stt_provider="qwen3_asr",
    )

    with TestClient(create_app(settings), client=("127.0.0.1", 50000)) as client:
        body = client.get("/health/ready").json()
        assert body["status"] == "ready"
        assert body["modules"]["speech"]["status"] == "idle"
        with client.websocket_connect("/api/v1/ws/practice-demo") as ws:
            message = ws.receive_json()
            assert message["type"] == "error"
            assert (
                client.get("/health/ready").json()["modules"]["speech"]["status"] == "unavailable"
            )


def test_ready_exposes_loaded_providers(client: TestClient) -> None:
    modules = client.get("/health/ready").json()["modules"]
    assert modules["gaze"]["status"] == "idle"
    assert modules["gaze"]["provider"] == "uniface"
    assert modules["speech"]["status"] == "idle"
    assert modules["speech"]["provider"] == "qwen3_asr"


def test_ready_exposes_successfully_loaded_real_provider(monkeypatch, tmp_path, fake_models):
    from app.ai.base import AIResult

    class Loaded:
        device = "cpu"

        async def infer(self, media):
            return AIResult("speech_rate", 0, "info", "", {})

    monkeypatch.setattr("app.main.create_local_qwen_speech_adapter", lambda *args: Loaded())
    settings = Settings(
        _env_file=None,
        app_env="development",
        vision_provider="uniface",
        stt_provider="qwen3_asr",
        database_url=f"sqlite+aiosqlite:///{tmp_path}/ready.db",
    )
    with TestClient(create_app(settings), client=("127.0.0.1", 50000)) as client:
        with client.websocket_connect("/api/v1/ws/practice-demo?protocol=2") as ws:
            send_v2(ws, "session.start", 1)
            ready = ws.receive_json()
            speech = ready["data"]["modules"]["speech"]
            assert speech["status"] == "ready"
            assert speech["provider"] == "qwen3_asr"
            assert speech["device"] == "cpu"


@pytest.mark.parametrize("app_env", ["development", "test", "production"])
@pytest.mark.parametrize("field", ["ai_mode", "vision_provider", "stt_provider"])
def test_mock_settings_are_rejected(app_env: str, field: str) -> None:
    with pytest.raises(ValidationError):
        Settings(_env_file=None, app_env=app_env, **{field: "mock"})


def test_unsupported_legacy_gaze_is_explicit() -> None:
    from app.main import create_local_gaze_adapter

    adapter = create_local_gaze_adapter(Settings(vision_provider="legacy"))
    assert "UNSUPPORTED_PROVIDER" in adapter.reason


def test_unknown_stt_provider_is_rejected_instead_of_using_mock() -> None:
    with pytest.raises(ValidationError):
        Settings(stt_provider="qwen3-asr")


def test_gaze_load_failure_is_unavailable_and_refuses_session(monkeypatch, tmp_path, fake_models):
    def unavailable(*_args, **_kwargs):
        raise RuntimeError("gaze model unavailable")

    monkeypatch.setattr("app.ai.uniface_gaze.UniFaceGazeAdapter", unavailable)
    monkeypatch.setattr("app.main.create_local_gaze_adapter", create_local_gaze_adapter)
    monkeypatch.setattr("app.main.create_local_qwen_speech_adapter", lambda *_: FakeSpeechAdapter())
    settings = Settings(
        _env_file=None,
        app_env="development",
        database_url=f"sqlite+aiosqlite:///{tmp_path}/gaze-failure.db",
    )
    with TestClient(create_app(settings), client=("127.0.0.1", 50000)) as client:
        modules = client.get("/health/ready").json()["modules"]
        assert modules["gaze"]["status"] == "idle"
        assert modules["speech"]["status"] == "idle"
        with client.websocket_connect("/api/v1/ws/practice-demo?protocol=2") as ws:
            ws.send_json(
                {
                    "event": "session.start",
                    "version": 2,
                    "session_id": None,
                    "sequence": 1,
                    "timestamp_ms": 0,
                    "module": "system",
                    "level": "info",
                    "data": {},
                }
            )
            error = ws.receive_json()
            assert error["event"] == "error"
            assert error["data"]["code"] == "MODEL_UNAVAILABLE_OR_BUSY"
            modules = error["data"]["modules"]
            assert modules["gaze"]["status"] == "unavailable"
            assert "MODEL_LOAD_FAILED" in modules["gaze"]["reason"]
