from functools import lru_cache
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", case_sensitive=False)

    app_name: str = "Realtime Feedback API"
    app_env: Literal["development", "test", "production"] = "development"
    api_prefix: str = "/api/v1"
    database_url: str = "sqlite+aiosqlite:///./feedback.db"
    redis_url: str | None = None
    redis_required: bool = False
    auto_create_tables: bool = True

    jwt_secret: str = "development-only-secret-change-me-now"
    jwt_algorithm: str = "HS256"
    access_token_minutes: int = 15
    refresh_token_days: int = 14

    cors_origins: list[str] = Field(default_factory=lambda: ["http://localhost:3000"])
    ai_mode: Literal["mock", "http"] = "mock"
    ai_base_url: str = "http://localhost:9000"
    ai_connect_timeout_seconds: float = 1.0
    ai_read_timeout_seconds: float = 2.0
    ai_max_retries: int = 2
    vision_provider: str = "mock"
    stt_provider: str = "mock"
    pronunciation_provider: str = "alignment"
    llm_provider: str = "mock"
    llm_base_url: str | None = None
    llm_api_key: str | None = None
    llm_model: str | None = None

    video_queue_size: int = 3
    audio_queue_size: int = 8
    audio_queue_wait_seconds: float = 0.1
    pipeline_grace_seconds: float = 2.0
    max_media_message_bytes: int = 2 * 1024 * 1024
    max_json_message_bytes: int = 64 * 1024
    max_connections_per_session: int = 2
    max_realtime_messages_per_second: int = 30
    video_sample_fps: float = 3.0
    audio_chunk_ms: int = 750
    module_timeout_seconds: float = 3.0
    max_script_chars: int = 20_000
    min_time_limit_seconds: int = 30
    max_time_limit_seconds: int = 3_600

    turn_url: str | None = None
    turn_username: str | None = None
    turn_credential: str | None = None

    @field_validator("jwt_secret")
    @classmethod
    def secure_production_secret(cls, value: str, info: object) -> str:
        # Cross-field production validation is also performed at app startup.
        if len(value) < 16:
            raise ValueError("JWT_SECRET must contain at least 16 characters")
        return value


@lru_cache
def get_settings() -> Settings:
    return Settings()
