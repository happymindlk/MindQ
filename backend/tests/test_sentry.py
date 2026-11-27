"""Sentry optional init + protected debug trigger."""
from __future__ import annotations

import pytest
from httpx import AsyncClient

from app.config import Settings
from app.sentry_init import _before_send, init_sentry


def test_init_sentry_noop_without_dsn():
    """Empty DSN must not raise and must leave Sentry uninitialized."""
    settings = Settings(SENTRY_DSN="")
    assert init_sentry(settings) is False


def test_init_sentry_noop_with_whitespace_dsn():
    settings = Settings(SENTRY_DSN="   ")
    assert init_sentry(settings) is False


def test_before_send_redacts_sensitive_request_fields():
    event = {
        "request": {
            "data": {
                "email": "candidate@example.com",
                "password": "secret-password",
                "otp_code": "123456",
                "responses": [{"q": 1, "answer": 4}],
            },
            "headers": {
                "Authorization": "Bearer abc",
                "Content-Type": "application/json",
            },
        },
        "extra": {"temp_token": "x" * 24, "path": "/api/v1/candidates/auth"},
    }
    scrubbed = _before_send(event, {})
    assert scrubbed is not None
    assert scrubbed["request"]["data"]["email"] == "candidate@example.com"
    assert scrubbed["request"]["data"]["password"] == "[Filtered]"
    assert scrubbed["request"]["data"]["otp_code"] == "[Filtered]"
    assert scrubbed["request"]["data"]["responses"] == "[Filtered]"
    assert scrubbed["request"]["headers"]["Authorization"] == "[Filtered]"
    assert scrubbed["request"]["headers"]["Content-Type"] == "application/json"
    assert scrubbed["extra"]["temp_token"] == "[Filtered]"
    assert scrubbed["extra"]["path"] == "/api/v1/candidates/auth"


@pytest.mark.asyncio
async def test_sentry_trigger_raises_in_non_production():
    """ASGITransport must not re-raise so the app's 500 handler can be asserted."""
    from httpx import ASGITransport
    from app.main import app

    transport = ASGITransport(app=app, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/v1/debug/sentry-trigger")
    assert response.status_code == 500
    body = response.json()
    assert body["detail"] == "Internal server error"


@pytest.mark.asyncio
async def test_sentry_trigger_forbidden_in_production_without_auth(
    async_client: AsyncClient, monkeypatch
):
    from app.api.v1 import debug as debug_module

    monkeypatch.setattr(debug_module.settings, "ENVIRONMENT", "production")
    response = await async_client.get("/api/v1/debug/sentry-trigger")
    assert response.status_code == 403
