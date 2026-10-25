"""Application configuration loaded exclusively from environment variables."""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime settings. Values come only from the process environment / .env."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_env: str = "development"
    database_url: str = "postgresql+asyncpg://localhost:5432/coaching_inquiry"
    log_level: str = "INFO"
    cie_encryption_key: str | None = None
    cie_contact_hash_key: str | None = None
    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = "llama3.2:latest"
    llm_timeout_seconds: float = 20
    llm_max_attempts: int = 3
    chat_allowed_origin: str = "http://localhost:3000"
    rate_limit_per_session_per_min: int = 10
    rate_limit_per_ip_per_min: int = 60
    job_max_attempts: int = 5


@lru_cache
def get_settings() -> Settings:
    """Return a cached Settings instance."""
    return Settings()
