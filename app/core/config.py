from functools import lru_cache
from typing import Literal

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Values that ship in documentation or compose files and must never reach production.
KNOWN_WEAK_SECRETS = frozenset(
    {
        "development-only-secret-change-me-now",
        "replace-with-at-least-32-random-characters",
        "changeme",
        "secret",
    }
)
PRODUCTION_SECRET_MIN_LENGTH = 32


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
    # Symmetric algorithms only: the secret is shared, so "none"/RS* would be a downgrade.
    jwt_algorithm: Literal["HS256", "HS384", "HS512"] = "HS256"
    access_token_minutes: int = 15
    refresh_token_days: int = 14
    auth_attempts_per_minute: int = Field(default=20, gt=0, le=1_000)
    # Enable only when a trusted reverse proxy overwrites X-Forwarded-For. Otherwise a
    # client could pick its own rate-limit bucket.
    trust_proxy_headers: bool = False

    cors_origins: list[str] = Field(
        default_factory=lambda: [
            "http://localhost:3000",
            "http://localhost:5173",
            "http://localhost:9000",
            "http://127.0.0.1:5173",
            "http://127.0.0.1:9000",
        ]
    )
    ai_mode: Literal["local", "http"] = "local"
    ai_base_url: str = "http://localhost:9000"
    ai_connect_timeout_seconds: float = 1.0
    ai_read_timeout_seconds: float = 2.0
    ai_max_retries: int = 2
    vision_provider: Literal["legacy", "uniface"] = "uniface"
    face_landmarker_path: str = ".models/face_landmarker.task"
    stt_provider: Literal["qwen3_asr"] = "qwen3_asr"
    stt_model: str = ".models/Qwen3-ASR-0.6B-Q8_0.gguf"
    stt_library_path: str = ".models/speech/libspeech.dylib"
    stt_device: str = "auto"
    stt_silence_rms_threshold: float = 0.003
    pronunciation_provider: str = "alignment"

    video_queue_size: int = 1
    audio_queue_size: int = 32
    audio_queue_wait_seconds: float = 0.1
    pipeline_grace_seconds: float = 30.0
    max_media_message_bytes: int = 2 * 1024 * 1024
    max_json_message_bytes: int = 64 * 1024
    max_connections_per_session: int = 2
    max_realtime_messages_per_second: int = 30
    video_sample_fps: float = 3.0
    audio_chunk_ms: int = 750
    module_timeout_seconds: float = 3.0
    max_script_chars: int = 20_000
    summary_server_path: str = ".models/llama/llama-server"
    summary_model_path: str = ".models/Qwen3.5-9B-Q4_K_M.gguf"
    summary_timeout_seconds: float = Field(default=600, gt=0, le=600)
    realtime_start_timeout_seconds: float = Field(default=120, gt=0, le=120)
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

    @model_validator(mode="after")
    def require_production_secret(self) -> "Settings":
        # A short or documented secret lets anyone mint tokens for any account.
        if self.app_env != "production":
            return self
        if len(self.jwt_secret) < PRODUCTION_SECRET_MIN_LENGTH:
            raise ValueError(
                f"JWT_SECRET must contain at least {PRODUCTION_SECRET_MIN_LENGTH} characters "
                "when APP_ENV=production"
            )
        if self.jwt_secret.strip().lower() in KNOWN_WEAK_SECRETS:
            raise ValueError(
                "JWT_SECRET is a documented placeholder and cannot be used in production"
            )
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
