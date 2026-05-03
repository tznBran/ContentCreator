"""Application configuration loaded from environment variables."""

from __future__ import annotations

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Top-level settings.

    Values are read from environment variables. The repo's ``.env`` file is
    loaded automatically when present.
    """

    model_config = SettingsConfigDict(
        env_file=("../../.env", ".env"),
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # API
    api_host: str = "0.0.0.0"
    api_port: int = 8000
    api_log_level: str = "info"
    api_cors_origins: str = "http://localhost:3000"

    # Persistence
    database_url: str = (
        "postgresql+psycopg://contentcreator:contentcreator@localhost:5432/contentcreator"
    )
    redis_url: str = "redis://localhost:6379/0"

    # Object storage (MinIO/S3)
    s3_endpoint_url: str = "http://localhost:9000"
    s3_region: str = "us-east-1"
    s3_access_key: str = "contentcreator"
    s3_secret_key: str = "contentcreator"
    s3_bucket: str = "contentcreator"
    s3_public_url: str = "http://localhost:9000/contentcreator"

    # OpenRouter
    openrouter_api_key: str = ""
    openrouter_video_model: str = "bytedance/seedance-2.0"
    openrouter_llm_model: str = "anthropic/claude-3.5-sonnet"
    openrouter_vision_model: str = "anthropic/claude-3.5-sonnet"
    openrouter_base_url: str = "https://openrouter.ai/api/v1"

    # TTS
    tts_provider: str = "f5tts"
    f5tts_device: str = "cuda"
    elevenlabs_api_key: str = ""
    replicate_api_token: str = ""

    # Social publishing
    youtube_client_id: str = ""
    youtube_client_secret: str = ""
    tiktok_client_key: str = ""
    tiktok_client_secret: str = ""
    meta_app_id: str = ""
    meta_app_secret: str = ""
    # Where the OAuth callback lives, e.g. "http://localhost:8000".
    # Provider-specific paths are appended automatically.
    oauth_redirect_base: str = "http://localhost:8000"
    # Where the frontend lives (used to redirect back after OAuth).
    web_base_url: str = "http://localhost:3000"
    # Optional: instagram graph user id (a.k.a. ``ig_user_id``) for the
    # Page-linked IG Business account. We could derive it via the Graph
    # API, but storing it explicitly avoids an extra call per publish.
    instagram_user_id: str = ""

    # Misc
    environment: str = Field(default="development")
    # When false, generation endpoints create rows but skip enqueueing RQ
    # tasks. Useful for unit tests.
    enqueue_jobs: bool = True

    @property
    def cors_origins_list(self) -> list[str]:
        return [o.strip() for o in self.api_cors_origins.split(",") if o.strip()]


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return a cached Settings instance."""
    return Settings()
