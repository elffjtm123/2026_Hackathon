import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.core.config import Settings
from app.main import create_app


def test_qwen_load_failure_does_not_start_with_mock_speech(
    monkeypatch: pytest.MonkeyPatch, tmp_path: object
) -> None:
    def unavailable(*_args: object) -> None:
        raise RuntimeError("Qwen unavailable")

    monkeypatch.setattr("app.main.create_local_qwen_speech_adapter", unavailable)
    settings = Settings(
        app_env="test",
        database_url=f"sqlite+aiosqlite:///{tmp_path}/test.db",
        redis_url=None,
        vision_provider="mock",
        stt_provider="qwen3_asr",
    )

    with pytest.raises(RuntimeError, match="Qwen unavailable"):
        with TestClient(create_app(settings)):
            pass


def test_unknown_stt_provider_is_rejected_instead_of_using_mock() -> None:
    with pytest.raises(ValidationError):
        Settings(stt_provider="qwen3-asr")
