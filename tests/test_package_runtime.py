import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from starlette.websockets import WebSocketDisconnect

from app.realtime.events import SessionStartData


def test_app_import_without_root_stt(tmp_path):
    root = Path(__file__).resolve().parents[1]
    shutil.copytree(root / "app", tmp_path / "app", ignore=shutil.ignore_patterns("__pycache__"))
    env = {**os.environ, "PYTHONPATH": str(tmp_path)}
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "from app.main import create_app; "
            "from app.modules.pronunciation.service "
            "import estimate_stt_pronunciation_accuracy as f; "
            'assert f("안녕하세요",reference_text="안녕하세요")["method"] == "script_agreement"',
        ],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr


def test_feature_aliases_normalized_once():
    data = SessionStartData.model_validate(
        {
            "settings": {
                "gazeEnabled": False,
                "karaokeGuideEnabled": False,
                "speechRateEnabled": False,
                "fillerWordsEnabled": False,
            }
        }
    )
    assert data.settings.model_dump()["gaze_enabled"] is False
    assert data.settings.model_dump()["karaoke_guide_enabled"] is False
    assert data.settings.model_dump()["speech_rate_enabled"] is False
    assert data.settings.model_dump()["filler_words_enabled"] is False


@pytest.mark.parametrize("env", ["production", "test"])
def test_non_development_demo_disabled(client, env):
    client.app.state.settings.app_env = env
    with pytest.raises(WebSocketDisconnect) as error:
        with client.websocket_connect("/api/v1/ws/practice-demo?protocol=2"):
            pass
    assert error.value.code == 4403


def test_demo_requires_loopback_peer(client):
    from fastapi.testclient import TestClient

    with TestClient(client.app, client=("192.0.2.1", 12345)) as remote:
        with pytest.raises(WebSocketDisconnect) as error:
            with remote.websocket_connect("/api/v1/ws/practice-demo?protocol=2"):
                pass
        assert error.value.code == 4403


def test_demo_rejects_untrusted_browser_origin(client):
    with pytest.raises(WebSocketDisconnect) as error:
        with client.websocket_connect(
            "/api/v1/ws/practice-demo?protocol=2", headers={"origin": "https://untrusted.example"}
        ):
            pass
    assert error.value.code == 4403


def test_demo_accepts_explicitly_trusted_origin(client):
    from tests.test_session_flow import send_v2

    with client.websocket_connect(
        "/api/v1/ws/practice-demo?protocol=2", headers={"origin": "http://testserver"}
    ) as ws:
        send_v2(ws, "session.start", 1)
        assert ws.receive_json()["event"] == "session.ready"
