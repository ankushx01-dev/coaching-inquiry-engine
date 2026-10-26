"""Static embeddable chat page route."""

from __future__ import annotations

from html import escape
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from coaching_inquiry_engine.config import get_settings

router = APIRouter(tags=["chat-page"])
_CHAT_PAGE = Path(__file__).resolve().parents[3] / "static" / "chat.html"


@router.get("/chat", include_in_schema=False)
async def get_chat_page(request: Request) -> HTMLResponse:
    _ = request
    settings = get_settings()
    origin = settings.chat_allowed_origin
    html = _CHAT_PAGE.read_text(encoding="utf-8").replace(
        "{{display_name}}", escape(settings.institute_display_name)
    )
    response = HTMLResponse(content=html)
    frame_ancestors = "'self'"
    if origin:
        frame_ancestors = f"{frame_ancestors} {origin}"
    response.headers["Content-Security-Policy"] = (
        f"frame-ancestors {frame_ancestors}"
    )
    if "X-Frame-Options" in response.headers:
        del response.headers["X-Frame-Options"]
    return response
