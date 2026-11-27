"""Auth/OTP rate limits and lockouts: IP budgets, failure caps, Retry-After."""
from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import HTTPException

from app.database import get_db
from app.main import app
from app.security import (
    AuthFailureLimiter,
    RateLimiter,
    candidate_otp_email_limiter,
    candidate_otp_limiter,
    candidate_otp_verify_limiter,
    hr_login_failure_limiter,
    hr_otp_limiter,
    hr_otp_verify_limiter,
    login_limiter,
)
from app.services.admin_otp import MAX_ATTEMPTS, apply_otp_attempt, hash_otp, locked_message
from app.services.candidate_otp import CandidateOtpError
from app.services.hr_otp import HrOtpError

CANDIDATE_SEND = "/api/v1/candidates/auth/otp/send"
CANDIDATE_VERIFY = "/api/v1/candidates/auth/otp/verify"
HR_VERIFY = "/api/v1/hr/auth/otp/verify"

CANDIDATE_SEND_PAYLOAD = {
    "first_name": "Ada",
    "full_name": "Ada Lovelace",
    "email": "ada@example.com",
    "access_code": "HM-ABCDEF-1",
    "terms_accepted": True,
}
CANDIDATE_VERIFY_PAYLOAD = {
    **CANDIDATE_SEND_PAYLOAD,
    "temp_token": "t" * 24,
    "otp_code": "123456",
}
HR_VERIFY_PAYLOAD = {
    "email": "hr@example.com",
    "temp_token": "t" * 24,
    "otp_code": "000000",
}


async def _no_db() -> AsyncIterator[None]:
    yield None


def _challenge(otp: str = "123456"):
    challenge_id = uuid4()
    now = datetime.now(timezone.utc)
    return (
        SimpleNamespace(
            id=challenge_id,
            otp_hash=hash_otp(challenge_id, otp),
            expires_at=now.replace(year=now.year + 1),
            attempt_count=0,
            locked_until=None,
            consumed_at=None,
        ),
        now,
    )


@pytest.fixture(autouse=True)
def _reset_auth_limiters():
    for limiter in (
        login_limiter,
        candidate_otp_limiter,
        candidate_otp_email_limiter,
        candidate_otp_verify_limiter,
        hr_otp_limiter,
        hr_otp_verify_limiter,
        hr_login_failure_limiter,
    ):
        limiter.reset()
    yield
    for limiter in (
        login_limiter,
        candidate_otp_limiter,
        candidate_otp_email_limiter,
        candidate_otp_verify_limiter,
        hr_otp_limiter,
        hr_otp_verify_limiter,
        hr_login_failure_limiter,
    ):
        limiter.reset()


# --- Unit: limiter contracts -------------------------------------------------------


def test_rate_limiter_returns_429_with_retry_after():
    limiter = RateLimiter(max_requests=2, window_seconds=60)
    limiter.check("candidate_otp_send:198.51.100.1")
    limiter.check("candidate_otp_send:198.51.100.1")
    with pytest.raises(HTTPException) as exc:
        limiter.check("candidate_otp_send:198.51.100.1")
    assert exc.value.status_code == 429
    assert "Too many requests" in str(exc.value.detail)
    assert int(exc.value.headers["Retry-After"]) >= 1


def test_auth_failure_limiter_blocks_after_budget(caplog):
    limiter = AuthFailureLimiter(max_failures=5, window_seconds=60)
    key = "hr_login:198.51.100.9"
    for _ in range(5):
        limiter.record_failure(key)
    with pytest.raises(HTTPException) as exc:
        limiter.assert_allowed(key)
    assert exc.value.status_code == 429
    assert "failed login" in str(exc.value.detail).lower()
    assert int(exc.value.headers["Retry-After"]) >= 1
    assert any("auth_failure_recorded" in r.message for r in caplog.records)


def test_five_consecutive_wrong_otps_lock_for_window():
    row, now = _challenge("482916")
    for i in range(MAX_ATTEMPTS - 1):
        assert apply_otp_attempt(row, f"{i:06d}", now) == "rejected"
    assert apply_otp_attempt(row, "999999", now) == "locked"
    assert row.attempt_count == MAX_ATTEMPTS
    assert row.locked_until is not None
    assert row.otp_hash == ""
    assert apply_otp_attempt(row, "482916", now) == "locked"


# --- HTTP: rapid OTP request spam --------------------------------------------------


@pytest.mark.asyncio
async def test_candidate_otp_send_rate_limit_returns_429(async_client, monkeypatch):
    app.dependency_overrides[get_db] = _no_db
    candidate_otp_limiter.reset()
    monkeypatch.setattr(candidate_otp_limiter, "max_requests", 3)
    monkeypatch.setattr(candidate_otp_limiter, "window_seconds", 60)
    monkeypatch.setattr(candidate_otp_email_limiter, "max_requests", 100)

    from app.schemas.candidate import CandidateOtpChallengeResponse

    async def fake_request(_db, _access_code, _email, *, device_id=None):
        return CandidateOtpChallengeResponse(status="otp_required", temp_token="t" * 24)

    monkeypatch.setattr("app.api.v1.candidate_auth.request_candidate_otp", fake_request)
    try:
        for _ in range(3):
            res = await async_client.post(CANDIDATE_SEND, json=CANDIDATE_SEND_PAYLOAD)
            assert res.status_code == 200
        res = await async_client.post(CANDIDATE_SEND, json=CANDIDATE_SEND_PAYLOAD)
        assert res.status_code == 429
        assert res.headers.get("retry-after")
        assert "too many" in res.json()["detail"].lower()
    finally:
        app.dependency_overrides.pop(get_db, None)
        candidate_otp_limiter.reset()


@pytest.mark.asyncio
async def test_candidate_otp_send_email_rate_limit_returns_429(async_client, monkeypatch):
    app.dependency_overrides[get_db] = _no_db
    candidate_otp_email_limiter.reset()
    monkeypatch.setattr(candidate_otp_limiter, "max_requests", 100)
    monkeypatch.setattr(candidate_otp_email_limiter, "max_requests", 2)
    monkeypatch.setattr(candidate_otp_email_limiter, "window_seconds", 60)

    from app.schemas.candidate import CandidateOtpChallengeResponse

    async def fake_request(_db, _access_code, _email, *, device_id=None):
        return CandidateOtpChallengeResponse(status="otp_required", temp_token="t" * 24)

    monkeypatch.setattr("app.api.v1.candidate_auth.request_candidate_otp", fake_request)
    try:
        for _ in range(2):
            assert (
                await async_client.post(CANDIDATE_SEND, json=CANDIDATE_SEND_PAYLOAD)
            ).status_code == 200
        res = await async_client.post(CANDIDATE_SEND, json=CANDIDATE_SEND_PAYLOAD)
        assert res.status_code == 429
        assert res.headers.get("retry-after")
    finally:
        app.dependency_overrides.pop(get_db, None)
        candidate_otp_email_limiter.reset()


# --- HTTP: OTP verify lockout + HR failure budget ----------------------------------


@pytest.mark.asyncio
async def test_candidate_wrong_otp_lockout_returns_429(async_client, monkeypatch, caplog):
    app.dependency_overrides[get_db] = _no_db
    for limiter in (login_limiter, candidate_otp_verify_limiter):
        monkeypatch.setattr(limiter, "max_requests", 100)

    async def fake_verify(_db, **kwargs):
        if kwargs["otp_code"] == "999999":
            raise CandidateOtpError(429, locked_message())
        raise CandidateOtpError(401, "Invalid or expired verification code")

    monkeypatch.setattr("app.api.v1.candidate_auth.verify_candidate_challenge", fake_verify)
    try:
        res = await async_client.post(
            CANDIDATE_VERIFY, json={**CANDIDATE_VERIFY_PAYLOAD, "otp_code": "999999"}
        )
        assert res.status_code == 429
        assert res.headers.get("retry-after")
        assert "locked" in res.json()["detail"].lower()
        assert any("candidate_auth_blocked" in r.message for r in caplog.records)
    finally:
        app.dependency_overrides.pop(get_db, None)


@pytest.mark.asyncio
async def test_hr_failed_login_attempts_are_rate_limited(async_client, monkeypatch):
    app.dependency_overrides[get_db] = _no_db
    hr_login_failure_limiter.reset()
    monkeypatch.setattr(hr_otp_verify_limiter, "max_requests", 100)
    monkeypatch.setattr(hr_login_failure_limiter, "max_failures", 5)
    monkeypatch.setattr(hr_login_failure_limiter, "window_seconds", 60)

    async def fake_verify(_db, **_kwargs):
        raise HrOtpError(401, "Invalid or expired verification code")

    monkeypatch.setattr("app.api.v1.hr_auth.verify_hr_challenge", fake_verify)
    try:
        for _ in range(5):
            res = await async_client.post(HR_VERIFY, json=HR_VERIFY_PAYLOAD)
            assert res.status_code == 401
        res = await async_client.post(HR_VERIFY, json=HR_VERIFY_PAYLOAD)
        assert res.status_code == 429
        assert res.headers.get("retry-after")
        assert "failed login" in res.json()["detail"].lower()
    finally:
        app.dependency_overrides.pop(get_db, None)
        hr_login_failure_limiter.reset()


@pytest.mark.asyncio
async def test_candidate_rapid_verify_hits_login_limiter(async_client, monkeypatch):
    app.dependency_overrides[get_db] = _no_db
    login_limiter.reset()
    monkeypatch.setattr(login_limiter, "max_requests", 2)
    monkeypatch.setattr(login_limiter, "window_seconds", 60)
    monkeypatch.setattr(candidate_otp_verify_limiter, "max_requests", 100)

    async def fake_verify(_db, **_kwargs):
        raise CandidateOtpError(401, "Invalid or expired verification code")

    monkeypatch.setattr("app.api.v1.candidate_auth.verify_candidate_challenge", fake_verify)
    try:
        for _ in range(2):
            assert (
                await async_client.post(CANDIDATE_VERIFY, json=CANDIDATE_VERIFY_PAYLOAD)
            ).status_code == 401
        res = await async_client.post(CANDIDATE_VERIFY, json=CANDIDATE_VERIFY_PAYLOAD)
        assert res.status_code == 429
        assert res.headers.get("retry-after")
    finally:
        app.dependency_overrides.pop(get_db, None)
        login_limiter.reset()
