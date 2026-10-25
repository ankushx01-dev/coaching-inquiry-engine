"""Static embeddable chat page route."""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import FileResponse

from coaching_inquiry_engine.config import get_settings

router = APIRouter(tags=["chat-page"])
_CHAT_PAGE = Path(__file__).resolve().parents[3] / "static" / "chat.html"


@router.get("/chat", include_in_schema=False)
async def get_chat_page(request: Request) -> FileResponse:
    _ = request
    origin = get_settings().chat_allowed_origin
    response = FileResponse(_CHAT_PAGE, media_type="text/html")
    frame_ancestors = "'self'"
    if origin:
        frame_ancestors = f"{frame_ancestors} {origin}"
    response.headers["Content-Security-Policy"] = (
        f"frame-ancestors {frame_ancestors}"
    )
    if "X-Frame-Options" in response.headers:
        del response.headers["X-Frame-Options"]
    return response
