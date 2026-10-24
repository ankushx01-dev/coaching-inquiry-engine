"""ASGI application entrypoint."""

from fastapi import FastAPI

from coaching_inquiry_engine.api.health import router as health_router
from coaching_inquiry_engine.config import get_settings
from coaching_inquiry_engine.db.encryption import require_crypto_settings
from coaching_inquiry_engine.logging import configure_logging


def create_app() -> FastAPI:
    """Build the API. Refuses to start without contact encryption keys."""
    settings = get_settings()
    require_crypto_settings(settings)
    configure_logging(settings.log_level)
    application = FastAPI(
        title="Coaching Inquiry Engine",
        version="0.1.0",
    )
    application.include_router(health_router)
    return application


app = create_app()
