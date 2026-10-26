"""Admin authentication, validation, and escaped rendering checks."""

from __future__ import annotations

from uuid import uuid4

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from coaching_inquiry_engine.api.admin_routes import (
    _DETAIL_TEMPLATE,
    StatusUpdate,
    router,
)
from coaching_inquiry_engine.config import Settings
from coaching_inquiry_engine.domain.exam_menu import load_exam_menu
from coaching_inquiry_engine.services.admin_auth import (
    AdminAuthRateLimiter,
    hash_admin_password,
    verify_admin_password,
)


def _app(*, app_env: str = "test") -> FastAPI:
    settings = Settings(
        _env_file=None,
        app_env=app_env,
        admin_enabled=True,
        admin_username="staff-user",
        admin_password_hash=hash_admin_password("secret", iterations=100_000),
    )
    application = FastAPI()
    application.state.settings = settings
    application.state.admin_auth_limiter = AdminAuthRateLimiter(limit=5)
    application.state.exam_menu = load_exam_menu("data/exams.yaml")
    application.state.admin_sessions = None
    application.state.contact_cipher = None
    application.include_router(router)
    return application


async def test_admin_endpoints_require_credentials_before_data_access() -> None:
    app = _app()
    request_id = uuid4()
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        responses = [
            await client.get("/admin/requests"),
            await client.get(f"/admin/requests/{request_id}"),
            await client.post(
                f"/admin/requests/{request_id}/status",
                json={"status": "contacted"},
            ),
        ]
    assert [response.status_code for response in responses] == [401, 401, 401]
    assert all(
        response.headers.get("www-authenticate") == "Basic"
        for response in responses
    )


async def test_authentication_errors_are_generic_and_rate_limited() -> None:
    app = _app()
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        wrong_user = await client.get(
            "/admin/requests", auth=("wrong-user", "secret")
        )
        wrong_password = await client.get(
            "/admin/requests", auth=("staff-user", "wrong")
        )
        assert wrong_user.status_code == wrong_password.status_code == 401
        assert wrong_user.json() == wrong_password.json()
        for _ in range(3):
            response = await client.get(
                "/admin/requests", auth=("wrong-user", "secret")
            )
        assert response.status_code == 429
        assert "staff-user" not in response.text


async def test_production_rejects_plain_http_even_before_basic_auth() -> None:
    async with AsyncClient(
        transport=ASGITransport(app=_app(app_env="production")),
        base_url="http://test",
    ) as client:
        response = await client.get("/admin/requests")
    assert response.status_code == 400
    assert response.json() == {"detail": "HTTPS required"}


def test_admin_settings_fail_with_missing_variable_names() -> None:
    with pytest.raises(ValueError, match="ADMIN_USERNAME"):
        Settings(_env_file=None, admin_enabled=True)
    with pytest.raises(ValueError, match="ADMIN_PASSWORD_HASH"):
        Settings(
            _env_file=None,
            admin_enabled=True,
            admin_username="staff-user",
        )


def test_password_hash_verification_and_status_payload_validation() -> None:
    encoded = hash_admin_password("secret", iterations=100_000)
    assert encoded != "secret"
    assert verify_admin_password("secret", encoded)
    assert not verify_admin_password("incorrect", encoded)
    with pytest.raises(ValueError):
        StatusUpdate.model_validate({"status": "unexpected"})
    with pytest.raises(ValueError):
        StatusUpdate.model_validate({"status": "new", "notes": "x" * 1001})
    with pytest.raises(ValueError):
        StatusUpdate.model_validate({"status": "new", "notes": "+919876543210"})
    with pytest.raises(ValueError):
        StatusUpdate.model_validate({"status": "new", "assigned_to": "a@b.com"})


def test_detail_template_escapes_user_controlled_values() -> None:
    rendered = _DETAIL_TEMPLATE.render(
        detail={"name": "<script>alert(1)</script>", "request_id": "id"},
        consents=[],
        messages=[],
        statuses=["new"],
    )
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in rendered
    assert "<script>alert(1)</script>" not in rendered


async def test_admin_router_is_not_registered_when_disabled(monkeypatch) -> None:
    from coaching_inquiry_engine.config import get_settings
    from coaching_inquiry_engine.main import create_app

    monkeypatch.setenv("ADMIN_ENABLED", "false")
    get_settings.cache_clear()
    app = create_app()
    try:
        async with app.router.lifespan_context(app):
            assert all(not route.path.startswith("/admin") for route in app.routes)
    finally:
        get_settings.cache_clear()
