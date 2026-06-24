from fastapi.testclient import TestClient

from tests.conftest import bearer


def test_register_login_refresh_and_me(client: TestClient, auth: dict[str, object]) -> None:
    duplicate = client.post(
        "/api/v1/auth/register",
        json={"email": "user@example.com", "password": "other-password", "display_name": "중복"},
    )
    assert duplicate.status_code == 409
    assert duplicate.json()["error"]["code"] == "EMAIL_ALREADY_EXISTS"

    login = client.post(
        "/api/v1/auth/login",
        json={"email": "user@example.com", "password": "correct-horse-battery-staple"},
    )
    assert login.status_code == 200

    me = client.get("/api/v1/users/me", headers=bearer(auth))
    assert me.status_code == 200
    assert me.json()["display_name"] == "테스터"

    refreshed = client.post("/api/v1/auth/refresh", json={"refresh_token": auth["refresh_token"]})
    assert refreshed.status_code == 200
    reused = client.post("/api/v1/auth/refresh", json={"refresh_token": auth["refresh_token"]})
    assert reused.status_code == 401


def test_protected_endpoint_requires_auth(client: TestClient) -> None:
    response = client.get("/api/v1/sessions")
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "AUTH_REQUIRED"
