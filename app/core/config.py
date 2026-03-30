from pydantic_settings import BaseSettings
from functools import lru_cache


class Settings(BaseSettings):
    # Database
    DATABASE_URL: str = "postgresql+asyncpg://emotionflow:emotionflow_secret@localhost:5433/emotionflow"
    SYNC_DATABASE_URL: str = "postgresql+psycopg2://emotionflow:emotionflow_secret@localhost:5433/emotionflow"

    # Redis
    REDIS_URL: str = "redis://localhost:6380/0"

    # JWT
    JWT_SECRET_KEY: str = "change-me-in-production-use-openssl-rand-hex-32"
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7

    # Upload
    MAX_UPLOAD_SIZE_MB: int = 50
    ALLOWED_AUDIO_TYPES: list[str] = ["audio/mpeg", "audio/wav", "audio/x-wav", "audio/mp4", "audio/flac", "audio/x-flac"]
    ALLOWED_EXTENSIONS: list[str] = [".mp3", ".wav", ".m4a", ".flac"]

    # AI / Gemini
    GEMINI_API_KEY: str = ""

    # Environment
    ENVIRONMENT: str = "development"

    # Rate limiting
    RATE_LIMIT_PER_MINUTE: int = 30
    RATE_LIMIT_BURST: int = 10

    # Upload
    UPLOAD_DIR: str = ""

    # Worker
    MODEL_TIER: str = "balanced"  # fast, balanced, max
    WORKER_SECRET: str = ""  # shared secret for internal worker endpoints
    API_BASE_URL: str = "http://localhost:8000"  # worker uses this to download audio

    # CORS
    CORS_ORIGINS: str = ""  # comma-separated, e.g. "https://example.com,http://localhost:3000"

    # Billing (simulated cost per completed job, USD)
    TIER_COST_FAST: float = 0.001
    TIER_COST_BALANCED: float = 0.005
    TIER_COST_MAX: float = 0.020

    model_config = {
        "env_file": ".env",
        "extra": "ignore",
    }


@lru_cache()
def get_settings() -> Settings:
    return Settings()
