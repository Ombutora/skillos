from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="SKILLOS_", extra="ignore")

    env: str = "development"
    database_url: str = "sqlite:///./skillos.db"
    redis_url: str | None = None

    jwt_secret: str = "change-me-in-production-dev-only-secret-0000"
    jwt_algorithm: str = "HS256"
    access_token_minutes: int = 30
    refresh_token_days: int = 7

    storage_dir: Path = Path("./storage")
    max_upload_mb: int = 500
    allowed_video_types: tuple[str, ...] = ("video/mp4", "video/quicktime", "video/webm")
    max_evidence_image_mb: int = 8

    # OpenAI. Read without the SKILLOS_ prefix so the standard variable works.
    openai_api_key: str | None = None
    openai_model: str | None = None
    openai_transcription_model: str | None = None

    # Which provider handles chat/vision calls: "openai" or "hf" (Hugging Face Inference Providers).
    ai_provider: Literal["openai", "hf"] = "openai"
    # Hugging Face. HF_TOKEN is also read without the prefix.
    hf_token: str | None = None
    hf_model: str | None = None  # a vision-capable chat model, e.g. Qwen/Qwen2.5-VL-72B-Instruct
    hf_base_url: str = "https://router.huggingface.co/v1"

    # Local transcription with faster-whisper (e.g. "small"). Takes precedence over OpenAI transcription.
    whisper_model: str | None = None

    # Validation thresholds (deterministic, not AI-controlled).
    visual_confidence_threshold: float = 0.8
    extraction_confidence_warning: float = 0.6

    seed_demo_data: bool = True


@lru_cache
def get_settings() -> Settings:
    import os

    s = Settings()
    # Allow the standard OPENAI_* names.
    s.openai_api_key = s.openai_api_key or os.getenv("OPENAI_API_KEY")
    s.openai_model = s.openai_model or os.getenv("OPENAI_MODEL")
    s.openai_transcription_model = s.openai_transcription_model or os.getenv("OPENAI_TRANSCRIPTION_MODEL")
    s.hf_token = s.hf_token or os.getenv("HF_TOKEN")
    if s.env == "production" and s.jwt_secret.startswith("change-me-in-production"):
        raise RuntimeError("SKILLOS_JWT_SECRET must be set in production")
    return s
