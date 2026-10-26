"""Application configuration loaded exclusively from environment variables."""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime settings. Values come only from the process environment / .env."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_env: str = "development"
    admin_enabled: bool = False
    admin_username: str | None = None
    admin_password_hash: str | None = None
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
    messenger_provider: Literal["fake", "telegram"] = "fake"
    telegram_bot_token: str | None = None
    telegram_webhook_secret: str | None = None
    telegram_timeout_seconds: float = 10
    telegram_max_retries: int = 2
    telegram_retry_backoff_seconds: float = 0.25
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

    @model_validator(mode="after")
    def require_telegram_credentials(self) -> Settings:
        if self.messenger_provider == "telegram":
            missing = [
                name
                for name, value in (
                    ("TELEGRAM_BOT_TOKEN", self.telegram_bot_token),
                    ("TELEGRAM_WEBHOOK_SECRET", self.telegram_webhook_secret),
                )
                if value is None or not value.strip()
            ]
            if missing:
                raise ValueError(
                    f"{', '.join(missing)} required when MESSENGER_PROVIDER=telegram"
                )
        if self.admin_enabled:
            missing_admin = [
                name
                for name, value in (
                    ("ADMIN_USERNAME", self.admin_username),
                    ("ADMIN_PASSWORD_HASH", self.admin_password_hash),
                )
                if value is None or not value.strip()
            ]
            if missing_admin:
                raise ValueError(
                    f"{', '.join(missing_admin)} required when ADMIN_ENABLED=true"
                )
        return self


@lru_cache
def get_settings() -> Settings:
    """Return a cached Settings instance."""
    return Settings()
