"""Application configuration loaded exclusively from environment variables."""

from functools import lru_cache
from typing import Literal

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
    institute_display_name: str = "coaching-enquiry"
    rate_limit_per_session_per_min: int = 10
    rate_limit_per_ip_per_min: int = 60
    job_max_attempts: int = 5
    staff_alert_channel: Literal["email", "telegram"] = "email"
    crm_provider: Literal["fake", "hubspot"] = "fake"
    outbox_batch_size: int = 20
    outbox_base_backoff_seconds: float = 1.0
    knowledge_max_age_days: int = 30
    age_bands: list[str] = ["under 18", "18-21", "22-25", "26-30", "above 30"]
    qualification_options: list[str] = [
        "Class 10",
        "Class 12",
        "Diploma",
        "Undergraduate",
        "Graduate",
        "Postgraduate",
    ]


@lru_cache
def get_settings() -> Settings:
    """Return a cached Settings instance."""
    return Settings()
