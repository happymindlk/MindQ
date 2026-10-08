"""Candidate login requires a Supabase email-OTP token for the submitted email."""
from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from uuid import uuid4

import jwt
import pytest

from app.config import settings
from app.database import get_db
from app.main import app
from app.security import login_limiter

LOGIN_URL = "/api/v1/candidate/login"
PAYLOAD = {
    "first_name": "Ada",
    "full_name": "Ada Lovelace",
    "email": "ada@example.com",
    "access_code": "HM-ABCDEF-1",
}


def _supabase_token(
    email: str | None = "ada@example.com",
    *,
    secret: str | None = None,
    expires_in: timedelta = timedelta(minutes=5),
) -> str:
    now = datetime.now(timezone.utc)
    claims: dict[str, object] = {
        "sub": str(uuid4()),
        "aud": "authenticated",
        "role": "authenticated",
        "iat": now,
        "exp": now + expires_in,
    }
    if email is not None:
        claims["email"] = email
    return jwt.encode(claims, secret or settings.SUPABASE_JWT_SECRET, algorithm="HS256")


async def _no_db() -> AsyncIterator[None]:
    yield None


@pytest.fixture(autouse=True)
def _isolate(monkeypatch):
    login_limiter.reset()
    monkeypatch.setattr(login_limiter, "max_requests", 100)
    monkeypatch.setattr("app.api.v1.candidate.settings.CANDIDATE_OTP_REQUIRED", True)
    app.dependency_overrides[get_db] = _no_db
    calls: list[object] = []

    async def fake_login(_db, data):
        calls.append(data)
        candidate = SimpleNamespace(
            id=uuid4(),
            corporate_id=uuid4(),
            package_id=uuid4(),
            first_name=data.first_name,
            full_name=data.full_name,
            email=str(data.email),
            access_code=data.access_code,
            logged_in_at=datetime.now(timezone.utc),
            created_at=datetime.now(timezone.utc),
            token=None,
        )
        return candidate, False

    monkeypatch.setattr("app.api.v1.candidate.CandidateService.login", fake_login)
    yield calls
    app.dependency_overrides.pop(get_db, None)
    login_limiter.reset()


@pytest.mark.asyncio
async def test_missing_otp_token_is_rejected_before_login(async_client, _isolate):
    res = await async_client.post(LOGIN_URL, json=PAYLOAD)
    assert res.status_code == 401
    assert _isolate == []


@pytest.mark.asyncio
async def test_forged_otp_token_is_rejected(async_client, _isolate):
    token = _supabase_token(secret="z" * 48)
    res = await async_client.post(LOGIN_URL, json=PAYLOAD, headers={"Authorization": f"Bearer {token}"})
    assert res.status_code == 401
    assert _isolate == []


@pytest.mark.asyncio
async def test_expired_otp_token_is_rejected(async_client, _isolate):
    token = _supabase_token(expires_in=timedelta(minutes=-1))
    res = await async_client.post(LOGIN_URL, json=PAYLOAD, headers={"Authorization": f"Bearer {token}"})
    assert res.status_code == 401
    assert "expired" in res.json()["detail"].lower()


@pytest.mark.asyncio
async def test_otp_for_a_different_email_is_forbidden(async_client, _isolate):
    token = _supabase_token(email="mallory@example.com")
    res = await async_client.post(LOGIN_URL, json=PAYLOAD, headers={"Authorization": f"Bearer {token}"})
    assert res.status_code == 403
    assert _isolate == []


@pytest.mark.asyncio
async def test_otp_token_without_email_claim_is_forbidden(async_client, _isolate):
    token = _supabase_token(email=None)
    res = await async_client.post(LOGIN_URL, json=PAYLOAD, headers={"Authorization": f"Bearer {token}"})
    assert res.status_code == 403


@pytest.mark.asyncio
async def test_verified_otp_issues_candidate_token_case_insensitively(async_client, _isolate):
    token = _supabase_token(email="ADA@Example.com")
    res = await async_client.post(LOGIN_URL, json=PAYLOAD, headers={"Authorization": f"Bearer {token}"})
    assert res.status_code == 200
    body = res.json()
    assert body["token"]
    assert body["first_name"] == "Ada"
    assert body["full_name"] == "Ada Lovelace"
    assert len(_isolate) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("field", ["first_name", "full_name"])
async def test_blank_names_are_rejected(async_client, _isolate, field):
    token = _supabase_token()
    payload = {**PAYLOAD, field: "   "}
    res = await async_client.post(LOGIN_URL, json=payload, headers={"Authorization": f"Bearer {token}"})
    assert res.status_code == 422
    assert _isolate == []
