"""ASGI application entrypoint."""

from fastapi import FastAPI

from coaching_inquiry_engine.api.health import router as health_router

app = FastAPI(
    title="Coaching Inquiry Engine",
    version="0.1.0",
)
app.include_router(health_router)
