"""Single-device soft session lock for candidate OTP login."""
from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.database import get_db
from app.main import app
from app.security import (
    candidate_otp_limiter,
    candidate_otp_verify_limiter,
    login_limiter,
)
from app.services.candidate_session_lock import (
    ACTIVE_SESSION_WINDOW,
    DEVICE_SESSION_CONFLICT_DETAIL,
    clear_device_session,
    enforce_device_login,
    is_active_session,
)
from app.auth import get_current_candidate

SEND_URL = "/api/v1/candidates/auth/otp/send"
LOGIN_URL = "/api/v1/candidates/auth/otp/verify"
LOGOUT_URL = "/api/v1/candidate/logout"
SEND_PAYLOAD = {
    "first_name": "Ada",
    "full_name": "Ada Lovelace",
    "email": "ada@example.com",
    "access_code": "HM-ABCDEF-1",
    "terms_accepted": True,
}
PAYLOAD = {
    "first_name": "Ada",
    "full_name": "Ada Lovelace",
    "email": "ada@example.com",
    "access_code": "HM-ABCDEF-1",
    "temp_token": "t" * 24,
    "otp_code": "123456",
    "terms_accepted": True,
}


class _FakeSession:
    def __init__(self) -> None:
        self.added: list[object] = []
        self.commits = 0

    def add(self, row: object) -> None:
        self.added.append(row)

    async def commit(self) -> None:
        self.commits += 1

    async def refresh(self, row: object) -> None:
        return None

    async def execute(self, *_a, **_k):
        return SimpleNamespace(first=lambda: None, scalar_one_or_none=lambda: None)


def _candidate(
    *,
    active_device_id: str | None = None,
    session_last_seen_at: datetime | None = None,
) -> SimpleNamespace:
    now = datetime.now(timezone.utc)
    return SimpleNamespace(
        id=uuid4(),
        corporate_id=uuid4(),
        package_id=uuid4(),
        first_name="Ada",
        full_name="Ada Lovelace",
        email="ada@example.com",
        access_code="HM-ABCDEF-1",
        logged_in_at=now,
        terms_accepted_at=now,
        active_device_id=active_device_id,
        session_last_seen_at=session_last_seen_at,
        created_at=now,
        token=None,
    )


def test_is_active_session_respects_three_minute_window():
    now = datetime.now(timezone.utc)
    active = _candidate(
        active_device_id="device-a",
        session_last_seen_at=now - timedelta(minutes=2, seconds=50),
    )
    expired = _candidate(
        active_device_id="device-a",
        session_last_seen_at=now - ACTIVE_SESSION_WINDOW - timedelta(seconds=1),
    )
    assert is_active_session(active, now=now) is True
    assert is_active_session(expired, now=now) is False


def test_enforce_blocks_other_device_inside_window():
    now = datetime.now(timezone.utc)
    candidate = _candidate(
        active_device_id="device-a",
        session_last_seen_at=now,
    )
    from fastapi import HTTPException

    with pytest.raises(HTTPException) as exc:
        enforce_device_login(candidate, "device-b")
    assert exc.value.status_code == 409
    assert exc.value.detail == DEVICE_SESSION_CONFLICT_DETAIL


def test_enforce_allows_same_device_and_expired_lock():
    now = datetime.now(timezone.utc)
    same = _candidate(active_device_id="device-a", session_last_seen_at=now)
    enforce_device_login(same, "device-a")

    expired = _candidate(
        active_device_id="device-a",
        session_last_seen_at=now - ACTIVE_SESSION_WINDOW - timedelta(seconds=5),
    )
    enforce_device_login(expired, "device-b")


def test_clear_device_session_releases_lock():
    candidate = _candidate(
        active_device_id="device-a",
        session_last_seen_at=datetime.now(timezone.utc),
    )
    clear_device_session(candidate)
    assert candidate.active_device_id is None
    enforce_device_login(candidate, "device-b")


@pytest.fixture
def _otp_login_env(monkeypatch):
    for limiter in (
        login_limiter,
        candidate_otp_limiter,
        candidate_otp_verify_limiter,
    ):
        limiter.reset()
        monkeypatch.setattr(limiter, "max_requests", 100)

    state = {
        "candidate": _candidate(),
        "session": _FakeSession(),
    }

    async def _fake_db() -> AsyncIterator[_FakeSession]:
        yield state["session"]

    async def fake_verify(_db, **_kwargs):
        return None

    async def fake_login(_db, data):
        cand = state["candidate"]
        cand.first_name = data.first_name
        cand.full_name = data.full_name
        cand.email = str(data.email)
        cand.access_code = data.access_code
        return cand, False

    app.dependency_overrides[get_db] = _fake_db
    monkeypatch.setattr(
        "app.api.v1.candidate_auth.verify_candidate_challenge", fake_verify
    )
    monkeypatch.setattr("app.api.v1.candidate_auth.CandidateService.login", fake_login)
    yield state
    app.dependency_overrides.pop(get_db, None)
    app.dependency_overrides.pop(get_current_candidate, None)
    for limiter in (
        login_limiter,
        candidate_otp_limiter,
        candidate_otp_verify_limiter,
    ):
        limiter.reset()


@pytest.mark.asyncio
async def test_otp_send_returns_409_without_email_when_other_device_active(
    async_client, _otp_login_env, monkeypatch
):
    """Step 1 must reject before SES when another device holds the soft lock."""
    state = _otp_login_env
    now = datetime.now(timezone.utc)
    state["candidate"].active_device_id = "device-a"
    state["candidate"].session_last_seen_at = now

    email_calls: list[tuple[str, str]] = []

    async def fake_validate(_db, _access_code, _email):
        return None

    async def fake_find(_db, _access_code, _email):
        return state["candidate"]

    async def fake_send_email(to_email: str, otp: str) -> None:
        email_calls.append((to_email, otp))

    monkeypatch.setattr(
        "app.services.candidate_otp._validate_login_target", fake_validate
    )
    monkeypatch.setattr(
        "app.services.candidate_otp._find_existing_login_candidate", fake_find
    )
    monkeypatch.setattr(
        "app.services.candidate_otp.send_candidate_otp_email", fake_send_email
    )

    blocked = await async_client.post(
        SEND_URL,
        json=SEND_PAYLOAD,
        headers={"X-Device-Id": "device-b"},
    )
    assert blocked.status_code == 409
    assert blocked.json()["detail"] == DEVICE_SESSION_CONFLICT_DETAIL
    assert email_calls == []
    assert state["session"].added == []
    assert state["session"].commits == 0


@pytest.mark.asyncio
async def test_second_device_login_returns_409_within_window(async_client, _otp_login_env):
    state = _otp_login_env
    first = await async_client.post(
        LOGIN_URL,
        json=PAYLOAD,
        headers={"X-Device-Id": "device-a"},
    )
    assert first.status_code == 200
    assert state["candidate"].active_device_id == "device-a"
    assert state["candidate"].session_last_seen_at is not None

    second = await async_client.post(
        LOGIN_URL,
        json=PAYLOAD,
        headers={"X-Device-Id": "device-b"},
    )
    assert second.status_code == 409
    assert second.json()["detail"] == DEVICE_SESSION_CONFLICT_DETAIL


@pytest.mark.asyncio
async def test_logout_releases_lock_for_second_device(async_client, _otp_login_env):
    state = _otp_login_env
    first = await async_client.post(
        LOGIN_URL,
        json=PAYLOAD,
        headers={"X-Device-Id": "device-a"},
    )
    assert first.status_code == 200
    token = first.json()["token"]

    async def _current():
        return state["candidate"]

    app.dependency_overrides[get_current_candidate] = _current
    logout = await async_client.post(
        LOGOUT_URL,
        headers={"Authorization": f"Bearer {token}", "X-Device-Id": "device-a"},
    )
    assert logout.status_code == 200
    assert state["candidate"].active_device_id is None

    second = await async_client.post(
        LOGIN_URL,
        json=PAYLOAD,
        headers={"X-Device-Id": "device-b"},
    )
    assert second.status_code == 200
    assert state["candidate"].active_device_id == "device-b"


@pytest.mark.asyncio
async def test_expired_session_allows_second_device(async_client, _otp_login_env):
    state = _otp_login_env
    first = await async_client.post(
        LOGIN_URL,
        json=PAYLOAD,
        headers={"X-Device-Id": "device-a"},
    )
    assert first.status_code == 200
    state["candidate"].session_last_seen_at = (
        datetime.now(timezone.utc) - ACTIVE_SESSION_WINDOW - timedelta(seconds=2)
    )

    second = await async_client.post(
        LOGIN_URL,
        json=PAYLOAD,
        headers={"X-Device-Id": "device-b"},
    )
    assert second.status_code == 200
    assert state["candidate"].active_device_id == "device-b"
