"""Tests for fail-closed config, rate limits, and security headers."""
from __future__ import annotations

import pytest
from fastapi import HTTPException
from starlette.requests import Request

from app.config import Settings
from app.security import (
    RateLimiter,
    assert_production_ready,
    enforce_rate_limit,
    login_limiter,
)


def test_assert_production_ready_skips_when_debug():
    settings = Settings(
        DEBUG=True,
        SECRET_KEY="dev-secret-key-change-in-production",
        SUPABASE_JWT_SECRET="super-secret-jwt-token-with-at-least-32-characters-long",
        CORS_ORIGINS="http://localhost:5173",
    )
    assert_production_ready(settings)  # must not raise


def test_assert_production_ready_rejects_weak_secrets():
    settings = Settings(
        DEBUG=False,
        SECRET_KEY="dev-secret-key-change-in-production",
        SUPABASE_JWT_SECRET="x" * 40,
        CORS_ORIGINS="https://app.example.com",
    )
    with pytest.raises(RuntimeError, match="SECRET_KEY"):
        assert_production_ready(settings)


def test_assert_production_ready_rejects_localhost_cors():
    settings = Settings(
        DEBUG=False,
        SECRET_KEY="x" * 40,
        SUPABASE_JWT_SECRET="y" * 40,
        CORS_ORIGINS="http://localhost:5173,http://127.0.0.1:3000",
    )
    with pytest.raises(RuntimeError, match="CORS_ORIGINS"):
        assert_production_ready(settings)


def test_assert_production_ready_accepts_strong_production_config():
    settings = Settings(
        DEBUG=False,
        SECRET_KEY="x" * 40,
        SUPABASE_JWT_SECRET="y" * 40,
        CORS_ORIGINS="https://app.example.com",
    )
    assert_production_ready(settings)


def test_assert_production_ready_rejects_disabled_candidate_otp():
    settings = Settings(
        DEBUG=False,
        SECRET_KEY="x" * 40,
        SUPABASE_JWT_SECRET="y" * 40,
        CORS_ORIGINS="https://app.example.com",
        CANDIDATE_OTP_REQUIRED=False,
    )
    with pytest.raises(RuntimeError, match="CANDIDATE_OTP_REQUIRED"):
        assert_production_ready(settings)


def test_rate_limiter_trips_after_budget():
    limiter = RateLimiter(max_requests=2, window_seconds=60)
    limiter.check("k")
    limiter.check("k")
    with pytest.raises(HTTPException) as exc:
        limiter.check("k")
    assert exc.value.status_code == 429


def _request(client_host: str = "203.0.113.10") -> Request:
    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "GET",
        "scheme": "http",
        "path": "/",
        "raw_path": b"/",
        "query_string": b"",
        "headers": [],
        "client": (client_host, 12345),
        "server": ("test", 80),
    }
    return Request(scope)


def test_enforce_rate_limit_uses_client_ip(monkeypatch):
    limiter = RateLimiter(max_requests=1, window_seconds=60)
    enforce_rate_limit(limiter, _request("198.51.100.1"), "unit")
    with pytest.raises(HTTPException) as exc:
        enforce_rate_limit(limiter, _request("198.51.100.1"), "unit")
    assert exc.value.status_code == 429
    # Different IP still allowed.
    enforce_rate_limit(limiter, _request("198.51.100.2"), "unit")


@pytest.mark.asyncio
async def test_health_and_security_headers(async_client):
    res = await async_client.get("/health")
    assert res.status_code == 200
    assert res.headers.get("x-content-type-options") == "nosniff"
    assert res.headers.get("x-frame-options") == "DENY"
    assert res.headers.get("x-request-id")


@pytest.mark.asyncio
async def test_login_rate_limit_returns_429(async_client, monkeypatch):
    login_limiter.reset()
    monkeypatch.setattr(login_limiter, "max_requests", 2)
    monkeypatch.setattr(login_limiter, "window_seconds", 60)
    monkeypatch.setattr("app.api.v1.candidate.settings.CANDIDATE_OTP_REQUIRED", False)

    async def fake_login(_db, _data):
        raise ValueError("Invalid access code")

    monkeypatch.setattr(
        "app.api.v1.candidate.CandidateService.login",
        fake_login,
    )

    payload = {
        "first_name": "Rate",
        "full_name": "Rate Limit",
        "email": "rate@example.com",
        "access_code": "HM-N0PE-Z",
    }
    for _ in range(2):
        res = await async_client.post("/api/v1/candidate/login", json=payload)
        assert res.status_code == 400
    res = await async_client.post("/api/v1/candidate/login", json=payload)
    assert res.status_code == 429
    login_limiter.reset()
    monkeypatch.setattr(login_limiter, "max_requests", 10)
    monkeypatch.setattr(login_limiter, "window_seconds", 15 * 60)
