import os
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.main import create_app


@pytest.fixture
def client(tmp_path: object) -> Iterator[TestClient]:
    database_path = os.path.join(str(tmp_path), "test.db")
    settings = Settings(
        app_env="test",
        database_url=f"sqlite+aiosqlite:///{database_path}",
        redis_url=None,
        auto_create_tables=True,
        jwt_secret="test-secret-that-is-definitely-long-enough",
        cors_origins=["http://testserver"],
        ai_mode="mock",
    )
    with TestClient(create_app(settings)) as test_client:
        yield test_client


@pytest.fixture
def auth(client: TestClient) -> dict[str, object]:
    response = client.post(
        "/api/v1/auth/register",
        json={
            "email": "user@example.com",
            "password": "correct-horse-battery-staple",
            "display_name": "테스터",
        },
    )
    assert response.status_code == 201
    return response.json()


def bearer(auth: dict[str, object]) -> dict[str, str]:
    return {"Authorization": f"Bearer {auth['access_token']}"}
