"""ASGI application entrypoint."""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from coaching_inquiry_engine.adapters.clock import SystemClock
from coaching_inquiry_engine.adapters.rate_limiter_memory import InMemoryRateLimiter
from coaching_inquiry_engine.api.chat_page import router as chat_page_router
from coaching_inquiry_engine.api.chat_routes import router as chat_router
from coaching_inquiry_engine.api.health import router as health_router
from coaching_inquiry_engine.config import get_settings
from coaching_inquiry_engine.db.encryption import (
    ContactCipher,
    require_crypto_settings,
)
from coaching_inquiry_engine.db.session import create_engine, create_session_factory
from coaching_inquiry_engine.logging import configure_logging
from coaching_inquiry_engine.services.chat_service import ChatMessageService
from coaching_inquiry_engine.services.chat_store import PostgresChatStore


def create_app() -> FastAPI:
    """Build the API. Refuses to start without contact encryption keys."""
    settings = get_settings()
    require_crypto_settings(settings)
    configure_logging(settings.log_level)

    engine = create_engine(settings.database_url)
    sessions = create_session_factory(engine)

    @asynccontextmanager
    async def lifespan(_application: FastAPI):
        yield
        await engine.dispose()

    application = FastAPI(
        title="Coaching Inquiry Engine",
        version="0.1.0",
        lifespan=lifespan,
    )
    application.state.chat_message_service = ChatMessageService(
        PostgresChatStore(
            sessions, ContactCipher.from_settings(settings), clock=SystemClock()
        ),
        InMemoryRateLimiter(
            per_session_per_minute=settings.rate_limit_per_session_per_min,
            per_ip_per_minute=settings.rate_limit_per_ip_per_min,
        ),
    )
    application.add_middleware(
        CORSMiddleware,
        allow_origins=[settings.chat_allowed_origin],
        allow_methods=["GET", "POST"],
        allow_headers=["content-type"],
    )
    application.include_router(health_router)
    application.include_router(chat_router)
    application.include_router(chat_page_router)
    return application


app = create_app()
