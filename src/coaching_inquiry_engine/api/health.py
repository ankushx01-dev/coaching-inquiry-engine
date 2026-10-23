"""Liveness / readiness endpoints."""

from fastapi import APIRouter

router = APIRouter(tags=["health"])


@router.get("/healthz")
async def healthz() -> dict[str, str]:
    """Return a simple OK status for load balancers and probes."""
    return {"status": "ok"}
