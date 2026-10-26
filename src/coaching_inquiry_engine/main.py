"""ASGI application entrypoint."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from coaching_inquiry_engine.adapters.clock import SystemClock
from coaching_inquiry_engine.adapters.messenger_telegram import TelegramMessenger
from coaching_inquiry_engine.adapters.rate_limiter_memory import InMemoryRateLimiter
from coaching_inquiry_engine.api.admin_routes import router as admin_router
from coaching_inquiry_engine.api.chat_page import router as chat_page_router
from coaching_inquiry_engine.api.chat_routes import router as chat_router
from coaching_inquiry_engine.api.health import router as health_router
from coaching_inquiry_engine.api.telegram_webhook import router as telegram_router
from coaching_inquiry_engine.config import get_settings
from coaching_inquiry_engine.db.encryption import (
    ContactCipher,
    require_crypto_settings,
)
from coaching_inquiry_engine.db.session import create_engine, create_session_factory
from coaching_inquiry_engine.domain.exam_menu import load_exam_menu
from coaching_inquiry_engine.domain.quick_replies import load_quick_replies
from coaching_inquiry_engine.logging import configure_logging
from coaching_inquiry_engine.services.admin_auth import AdminAuthRateLimiter
from coaching_inquiry_engine.services.chat_service import ChatMessageService
from coaching_inquiry_engine.services.chat_store import PostgresChatStore
from coaching_inquiry_engine.services.telegram_webhook import TelegramWebhookService


def create_app() -> FastAPI:
    """Build the API. Refuses to start without contact encryption keys."""
    settings = get_settings()
    require_crypto_settings(settings)
    configure_logging(settings.log_level)

    engine = create_engine(settings.database_url)
    sessions = create_session_factory(engine)
    cipher = ContactCipher.from_settings(settings)

    @asynccontextmanager
    async def lifespan(_application: FastAPI) -> AsyncIterator[None]:
        yield
        await engine.dispose()

    application = FastAPI(
        title="Coaching Inquiry Engine",
        version="0.1.0",
        lifespan=lifespan,
    )
    quick_replies = tuple(load_quick_replies("data/quick_replies.yaml"))
    exam_menu = load_exam_menu("data/exams.yaml")
    application.state.chat_message_service = ChatMessageService(
        PostgresChatStore(
            sessions, cipher, clock=SystemClock()
        ),
        InMemoryRateLimiter(
            per_session_per_minute=settings.rate_limit_per_session_per_min,
            per_ip_per_minute=settings.rate_limit_per_ip_per_min,
        ),
        quick_replies,
        exam_menu=exam_menu,
        age_bands=tuple(settings.age_bands),
        qualification_options=tuple(settings.qualification_options),
    )
    application.state.telegram_webhook_secret = settings.telegram_webhook_secret or ""
    application.state.settings = settings
    application.state.exam_menu = exam_menu
    application.state.admin_sessions = sessions
    application.state.contact_cipher = cipher
    application.state.admin_auth_limiter = AdminAuthRateLimiter()
    if settings.messenger_provider == "telegram":
        telegram_messenger = TelegramMessenger(settings=settings)
        application.state.telegram_webhook_service = TelegramWebhookService(
            sessions,
            cipher,
            telegram_messenger,
            settings,
            SystemClock(),
            exam_menu,
            tuple(settings.qualification_options),
        )
    else:
        application.state.telegram_webhook_service = None
    application.add_middleware(
        CORSMiddleware,
        allow_origins=[settings.chat_allowed_origin],
        allow_methods=["GET", "POST"],
        allow_headers=["content-type"],
    )
    application.include_router(health_router)
    application.include_router(chat_router)
    application.include_router(chat_page_router)
    application.include_router(telegram_router)
    if settings.admin_enabled:
        application.include_router(admin_router)
    return application


app = create_app()
