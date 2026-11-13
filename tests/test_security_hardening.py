"""Regression tests for the credential, token and transport hardening."""

import re
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import jwt
import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.core.config import Settings
from app.core.security import verify_password_or_dummy
from tests.conftest import bearer

UUID_PATTERN = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")


def _signed(client: TestClient, payload: dict[str, object]) -> str:
    settings = client.app.state.settings
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def test_login_is_rate_limited_per_client(client: TestClient, auth: dict[str, object]) -> None:
    client.app.state.settings.auth_attempts_per_minute = 3
    body = {"email": "user@example.com", "password": "wrong-password"}
    codes = [client.post("/api/v1/auth/login", json=body).status_code for _ in range(4)]
    assert codes[:3] == [401, 401, 401]
    assert codes[3] == 429
    assert client.post("/api/v1/auth/login", json=body).json()["error"]["code"] == "RATE_LIMITED"


def test_unknown_account_uses_the_same_failure_path(client: TestClient) -> None:
    known = client.post(
        "/api/v1/auth/login",
        json={"email": "user@example.com", "password": "wrong-password"},
    )
    unknown = client.post(
        "/api/v1/auth/login",
        json={"email": "nobody@example.com", "password": "wrong-password"},
    )
    assert known.status_code == unknown.status_code == 401
    assert known.json()["error"]["code"] == unknown.json()["error"]["code"]


def test_spoofed_forwarded_header_cannot_escape_the_limit(
    client: TestClient, auth: dict[str, object]
) -> None:
    client.app.state.settings.auth_attempts_per_minute = 2
    body = {"email": "user@example.com", "password": "wrong-password"}
    codes = [
        client.post(
            "/api/v1/auth/login", json=body, headers={"X-Forwarded-For": f"10.0.0.{index}"}
        ).status_code
        for index in range(3)
    ]
    assert codes == [401, 401, 429]


def test_dummy_verification_never_reports_success() -> None:
    assert verify_password_or_dummy("anything", None) is False


def test_access_token_without_expiry_is_rejected(
    client: TestClient, auth: dict[str, object]
) -> None:
    now = datetime.now(timezone.utc)
    token = _signed(
        client,
        {
            "sub": auth["user"]["id"],
            "type": "access",
            "jti": str(uuid4()),
            "iat": now,
            "iss": client.app.state.settings.app_name,
        },
    )
    response = client.get("/api/v1/users/me", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 401


def test_malformed_subject_is_a_rejected_token_not_a_server_error(
    client: TestClient, auth: dict[str, object]
) -> None:
    now = datetime.now(timezone.utc)
    token = _signed(
        client,
        {
            "sub": "not-a-uuid",
            "type": "access",
            "jti": str(uuid4()),
            "iat": now,
            "exp": now + timedelta(minutes=5),
            "iss": client.app.state.settings.app_name,
        },
    )
    response = client.get("/api/v1/users/me", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "INVALID_TOKEN"


def test_api_responses_carry_baseline_security_headers(
    client: TestClient, auth: dict[str, object]
) -> None:
    response = client.get("/api/v1/users/me", headers=bearer(auth))
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["x-frame-options"] == "DENY"
    assert response.headers["referrer-policy"] == "no-referrer"
    assert response.headers["cache-control"] == "no-store"


def test_unsafe_request_id_is_not_reflected(client: TestClient) -> None:
    response = client.get("/health/live", headers={"X-Request-ID": "<script>alert(1)</script>"})
    assert response.headers["x-request-id"] != "<script>alert(1)</script>"
    assert UUID_PATTERN.fullmatch(response.headers["x-request-id"])


def test_safe_request_id_is_preserved(client: TestClient) -> None:
    response = client.get("/health/live", headers={"X-Request-ID": "req-abc.123"})
    assert response.headers["x-request-id"] == "req-abc.123"


def test_production_rejects_short_or_placeholder_secrets() -> None:
    with pytest.raises(ValidationError):
        Settings(_env_file=None, app_env="production", jwt_secret="x" * 20)
    with pytest.raises(ValidationError):
        Settings(
            _env_file=None,
            app_env="production",
            jwt_secret="development-only-secret-change-me-now",
        )
    assert (
        Settings(_env_file=None, app_env="production", jwt_secret="k" * 48).app_env == "production"
    )


def test_production_startup_refuses_a_downgraded_algorithm() -> None:
    with pytest.raises(ValidationError):
        Settings(_env_file=None, jwt_algorithm="none")


def test_refresh_token_rotation_stays_single_use(
    client: TestClient, auth: dict[str, object]
) -> None:
    first = client.post("/api/v1/auth/refresh", json={"refresh_token": auth["refresh_token"]})
    assert first.status_code == 200
    replay = client.post("/api/v1/auth/refresh", json={"refresh_token": auth["refresh_token"]})
    assert replay.status_code == 401
    # The rotated token still works, so rotation did not revoke the whole family.
    rotated = client.post(
        "/api/v1/auth/refresh", json={"refresh_token": first.json()["refresh_token"]}
    )
    assert rotated.status_code == 200


def test_blank_display_name_is_rejected(client: TestClient) -> None:
    response = client.post(
        "/api/v1/auth/register",
        json={
            "email": "blank@example.com",
            "password": "long-enough-password",
            "display_name": "   ",
        },
    )
    assert response.status_code == 422


def test_blank_session_title_is_rejected(client: TestClient, auth: dict[str, object]) -> None:
    response = client.post(
        "/api/v1/sessions",
        headers=bearer(auth),
        json={"type": "presentation", "title": "   "},
    )
    assert response.status_code == 422
