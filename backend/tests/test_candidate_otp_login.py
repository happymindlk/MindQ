"""Candidate login requires a verified custom OTP challenge for the email."""
from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.database import get_db
from app.main import app
from app.security import candidate_otp_limiter, candidate_otp_verify_limiter, login_limiter
from app.services.candidate_otp import CandidateOtpError

LOGIN_URL = "/api/v1/candidates/auth/otp/verify"
REQUEST_URL = "/api/v1/candidates/auth/otp/send"
SEND_PAYLOAD = {
    "first_name": "Ada",
    "full_name": "Ada Lovelace",
    "email": "ada@example.com",
    "access_code": "HM-ABCDEF-1",
}
PAYLOAD = {
    "first_name": "Ada",
    "full_name": "Ada Lovelace",
    "email": "ada@example.com",
    "access_code": "HM-ABCDEF-1",
    "temp_token": "t" * 24,
    "otp_code": "123456",
}


async def _no_db() -> AsyncIterator[None]:
    yield None


@pytest.fixture(autouse=True)
def _isolate(monkeypatch):
    for limiter in (login_limiter, candidate_otp_limiter, candidate_otp_verify_limiter):
        limiter.reset()
        monkeypatch.setattr(limiter, "max_requests", 100)
    app.dependency_overrides[get_db] = _no_db
    calls: list[object] = []
    verify_calls: list[dict] = []

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

    async def fake_verify(_db, **kwargs):
        verify_calls.append(kwargs)
        if kwargs["otp_code"] == "000000":
            raise CandidateOtpError(401, "Invalid or expired verification code")
        if kwargs["otp_code"] == "999999":
            raise CandidateOtpError(429, "Too many invalid codes. This sign-in is locked for 15 minutes.")
        if kwargs["temp_token"].startswith("bad-token"):
            raise CandidateOtpError(401, "Invalid or expired verification session")

    monkeypatch.setattr("app.api.v1.candidate_auth.CandidateService.login", fake_login)
    monkeypatch.setattr("app.api.v1.candidate_auth.verify_candidate_challenge", fake_verify)
    yield {"login": calls, "verify": verify_calls}
    app.dependency_overrides.pop(get_db, None)
    for limiter in (login_limiter, candidate_otp_limiter, candidate_otp_verify_limiter):
        limiter.reset()


@pytest.mark.asyncio
async def test_missing_temp_token_is_rejected_before_login(async_client, _isolate):
    payload = {k: v for k, v in PAYLOAD.items() if k != "temp_token"}
    res = await async_client.post(LOGIN_URL, json=payload)
    assert res.status_code == 422
    assert _isolate["login"] == []


@pytest.mark.asyncio
async def test_invalid_temp_token_is_rejected(async_client, _isolate):
    res = await async_client.post(LOGIN_URL, json={**PAYLOAD, "temp_token": "bad-token-000000000000"})
    assert res.status_code == 401
    assert "session" in res.json()["detail"].lower()
    assert _isolate["login"] == []


@pytest.mark.asyncio
async def test_wrong_code_is_rejected(async_client, _isolate):
    res = await async_client.post(LOGIN_URL, json={**PAYLOAD, "otp_code": "000000"})
    assert res.status_code == 401
    assert _isolate["login"] == []


@pytest.mark.asyncio
async def test_locked_challenge_returns_429(async_client, _isolate):
    res = await async_client.post(LOGIN_URL, json={**PAYLOAD, "otp_code": "999999"})
    assert res.status_code == 429
    assert _isolate["login"] == []


@pytest.mark.asyncio
async def test_verified_code_issues_candidate_token(async_client, _isolate):
    res = await async_client.post(LOGIN_URL, json=PAYLOAD)
    assert res.status_code == 200
    body = res.json()
    assert body["token"]
    assert body["first_name"] == "Ada"
    assert body["full_name"] == "Ada Lovelace"
    assert len(_isolate["login"]) == 1
    assert _isolate["verify"][0]["otp_code"] == "123456"


@pytest.mark.asyncio
@pytest.mark.parametrize("field", ["first_name", "full_name"])
async def test_blank_names_are_rejected(async_client, _isolate, field):
    payload = {**PAYLOAD, field: "   "}
    res = await async_client.post(LOGIN_URL, json=payload)
    assert res.status_code == 422
    assert _isolate["login"] == []


@pytest.mark.asyncio
async def test_request_code_returns_temp_token(async_client, monkeypatch):
    captured = {}

    from app.schemas.candidate import CandidateOtpChallengeResponse

    async def fake_request(_db, access_code, email):
        captured["access_code"] = access_code
        captured["email"] = email
        return CandidateOtpChallengeResponse(status="otp_required", temp_token="t" * 24)

    monkeypatch.setattr("app.api.v1.candidate_auth.request_candidate_otp", fake_request)
    res = await async_client.post(REQUEST_URL, json=SEND_PAYLOAD)
    assert res.status_code == 200
    assert res.json() == {"status": "otp_required", "temp_token": "t" * 24}
    assert captured == {"access_code": "HM-ABCDEF-1", "email": "ada@example.com"}


@pytest.mark.asyncio
async def test_request_code_maps_otp_errors(async_client, monkeypatch):
    async def fake_request(_db, *_args):
        raise CandidateOtpError(429, "Too many verification codes were requested. Try again later.")

    monkeypatch.setattr("app.api.v1.candidate_auth.request_candidate_otp", fake_request)
    res = await async_client.post(REQUEST_URL, json=SEND_PAYLOAD)
    assert res.status_code == 429


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "url",
    ["/api/v1/candidate/login", "/api/v1/candidate/otp/request"],
)
async def test_legacy_candidate_auth_routes_are_gone(async_client, url):
    res = await async_client.post(url, json={})
    assert res.status_code == 404
