"""Admin email OTP: code rules, withheld session, and the login HTTP contract."""
from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from uuid import uuid4

import jwt
import pytest
from fastapi import HTTPException

from app.auth import get_current_ops_user
from app.config import settings
from app.database import get_db
from app.main import app
from app.schemas.admin_auth import AdminLoginChallengeResponse, AdminTokenResponse
from app.security import admin_otp_limiter, admin_otp_verify_limiter
from app.services.admin_otp import (
    ADMIN_OTP_AUDIENCE,
    LOCKOUT,
    AdminLoginError,
    apply_otp_attempt,
    decode_admin_otp_token,
    generate_otp,
    hash_otp,
    issue_admin_otp_token,
    otp_matches,
    seal_secret,
    send_block_reason,
    unseal_secret,
)
from app.services.email import admin_otp_message, render_admin_otp_html
from app.services.supabase_password import (
    SupabaseAuthUnavailable,
    verify_supabase_password,
)

LOGIN_URL = "/api/v1/admin/auth/login"
VERIFY_URL = "/api/v1/admin/auth/verify-otp"


def _challenge(otp: str = "123456", *, expires_in: timedelta = timedelta(minutes=5)):
    now = datetime.now(timezone.utc)
    challenge_id = uuid4()
    return SimpleNamespace(
        id=challenge_id,
        otp_hash=hash_otp(challenge_id, otp),
        expires_at=now + expires_in,
        attempt_count=0,
        locked_until=None,
        consumed_at=None,
    ), now


def test_otp_is_six_digits_and_not_stored_as_plaintext():
    code = generate_otp()
    assert len(code) == 6 and code.isdigit()
    challenge_id = uuid4()
    stored = hash_otp(challenge_id, code)
    assert stored != code
    assert otp_matches(challenge_id, code, stored)
    assert not otp_matches(challenge_id, "000000", stored)
    assert not otp_matches(uuid4(), code, stored)
    assert not otp_matches(challenge_id, code, "")


def test_held_session_tokens_are_sealed():
    sealed = seal_secret("access-token-value")
    assert "access-token-value" not in sealed
    assert unseal_secret(sealed) == "access-token-value"
    assert unseal_secret(None) is None
    assert unseal_secret("not-a-fernet-token") is None


def test_email_body_is_the_admin_verification_sentence():
    assert admin_otp_message("123456") == (
        "Your MindQ Admin Verification Code is: 123456. Valid for 5 minutes."
    )
    html = render_admin_otp_html("123456")
    assert "Admin Portal" in html
    assert "123456" in html
    assert "The code will expire in 5 minutes." in html
    assert "<script>" not in render_admin_otp_html("<script>")


def test_three_invalid_codes_lock_for_fifteen_minutes_and_burn_the_code():
    row, now = _challenge("123456")
    assert apply_otp_attempt(row, "000001", now) == "rejected"
    assert apply_otp_attempt(row, "000002", now) == "rejected"
    assert apply_otp_attempt(row, "000003", now) == "locked"
    assert row.attempt_count == 3
    assert row.locked_until == now + LOCKOUT
    assert row.otp_hash == ""
    assert row.consumed_at == now
    assert apply_otp_attempt(row, "123456", now) == "locked"
    assert row.attempt_count == 3

    later = now + timedelta(minutes=16)
    assert apply_otp_attempt(row, "123456", later) == "consumed"
    assert row.attempt_count == 3


def test_correct_code_is_one_time_and_expired_codes_do_not_count():
    row, now = _challenge("654321")
    assert apply_otp_attempt(row, "000000", now) == "rejected"
    assert apply_otp_attempt(row, "654321", now) == "accepted"
    assert row.consumed_at == now
    assert apply_otp_attempt(row, "654321", now) == "consumed"

    expired, then = _challenge("111111", expires_in=timedelta(minutes=-1))
    assert apply_otp_attempt(expired, "111111", then) == "expired"
    assert expired.attempt_count == 0
    assert expired.otp_hash == ""


def test_send_cap_blocks_cooldown_then_window():
    now = datetime.now(timezone.utc)
    assert send_block_reason([], now) is None
    assert send_block_reason([now - timedelta(seconds=30)], now) == "cooldown"
    assert send_block_reason([now - timedelta(minutes=2)], now) is None
    window = [now - timedelta(minutes=2), now - timedelta(minutes=4), now - timedelta(minutes=6)]
    assert send_block_reason(window, now) == "window"


def test_temp_token_is_not_an_admin_session():
    challenge_id = uuid4()
    user_id = uuid4()
    token = issue_admin_otp_token(challenge_id, user_id)
    decoded_id, decoded_user = decode_admin_otp_token(token)
    assert decoded_id == challenge_id
    assert decoded_user == user_id
    payload = jwt.decode(
        token, settings.SECRET_KEY, algorithms=["HS256"], audience=ADMIN_OTP_AUDIENCE
    )
    assert payload["typ"] == "admin_otp"
    assert "otp" not in payload
    assert "access_token" not in payload

    forged = jwt.encode(
        {"sub": str(user_id), "challenge_id": str(challenge_id), "typ": "admin_otp",
         "aud": ADMIN_OTP_AUDIENCE, "exp": datetime.now(timezone.utc) + timedelta(minutes=5)},
        "not-the-server-secret-with-32-bytes!!",
        algorithm="HS256",
    )
    with pytest.raises(jwt.PyJWTError):
        decode_admin_otp_token(forged)

    expired = jwt.encode(
        {"sub": str(user_id), "challenge_id": str(challenge_id), "typ": "admin_otp",
         "aud": ADMIN_OTP_AUDIENCE, "exp": datetime.now(timezone.utc) - timedelta(minutes=1)},
        settings.SECRET_KEY,
        algorithm="HS256",
    )
    with pytest.raises(jwt.PyJWTError):
        decode_admin_otp_token(expired)


@pytest.mark.asyncio
async def test_ops_dependency_rejects_the_temp_token():
    token = issue_admin_otp_token(uuid4(), uuid4())
    with pytest.raises(HTTPException) as exc:
        await get_current_ops_user(authorization=f"Bearer {token}")
    assert exc.value.status_code == 401


class _Response:
    def __init__(self, status_code: int, payload: object = None, *, broken_json: bool = False):
        self.status_code = status_code
        self._payload = payload
        self._broken_json = broken_json

    def json(self):
        if self._broken_json:
            raise ValueError("not json")
        return self._payload


class _Client:
    response = _Response(400, {})
    calls: list[tuple] = []

    def __init__(self, *args, **kwargs):
        assert kwargs.get("follow_redirects") is False

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    async def post(self, url, headers=None, json=None):
        _Client.calls.append((url, headers, json))
        return _Client.response


@pytest.fixture
def _auth_settings(monkeypatch):
    monkeypatch.setattr(
        "app.services.supabase_password.settings.SUPABASE_URL", "http://auth.test"
    )
    monkeypatch.setattr(
        "app.services.supabase_password.settings.SUPABASE_SERVICE_ROLE_KEY", "service-role-test"
    )
    monkeypatch.setattr("app.services.supabase_password.httpx.AsyncClient", _Client)
    _Client.calls = []


@pytest.mark.asyncio
async def test_password_grant_hides_invalid_credentials(_auth_settings):
    _Client.response = _Response(400, {"error": "invalid_grant", "error_description": "Invalid login credentials"})
    assert await verify_supabase_password("ops@mindq.com", "wrong") is None
    assert _Client.calls[0][2]["password"] == "wrong"
    assert "grant_type=password" in _Client.calls[0][0]


@pytest.mark.asyncio
async def test_password_grant_returns_a_session_without_logging_the_body(_auth_settings):
    user_id = uuid4()
    _Client.response = _Response(
        200,
        {
            "access_token": "a" * 24,
            "refresh_token": "refresh-1",
            "expires_in": 3600,
            "user": {"id": str(user_id), "email": "OPS@mindq.com"},
            "extra": "ignored",
        },
    )
    session = await verify_supabase_password("ops@mindq.com", "secret")
    assert session is not None
    assert session.user_id == user_id
    assert session.email == "ops@mindq.com"
    assert session.access_token == "a" * 24
    assert session.expires_in == 3600


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "response",
    [
        _Response(200, {"access_token": "short", "refresh_token": "x", "expires_in": 10, "user": {}}),
        _Response(500, {"error": "upstream"}),
        _Response(302, {}),
        _Response(200, {"not": "json"}, broken_json=True),
    ],
)
async def test_password_grant_failures_are_unavailable(_auth_settings, response):
    _Client.response = response
    with pytest.raises(SupabaseAuthUnavailable):
        await verify_supabase_password("ops@mindq.com", "secret")


@pytest.mark.asyncio
async def test_password_grant_requires_configuration(monkeypatch):
    monkeypatch.setattr("app.services.supabase_password.settings.SUPABASE_SERVICE_ROLE_KEY", "")
    with pytest.raises(SupabaseAuthUnavailable):
        await verify_supabase_password("ops@mindq.com", "secret")


async def _no_db() -> AsyncIterator[None]:
    yield None


@pytest.fixture
def _routes(monkeypatch):
    admin_otp_limiter.reset()
    admin_otp_verify_limiter.reset()
    monkeypatch.setattr(admin_otp_limiter, "max_requests", 100)
    monkeypatch.setattr(admin_otp_verify_limiter, "max_requests", 100)
    app.dependency_overrides[get_db] = _no_db
    calls: list[tuple] = []

    async def fake_start(_db, email, password):
        calls.append(("login", email, password))
        if password == "wrong":
            raise AdminLoginError(401, "Invalid email or password")
        return AdminLoginChallengeResponse(status="otp_required", temp_token="t" * 24)

    async def fake_verify(_db, token, code):
        calls.append(("verify", token, code))
        if code == "000000":
            raise AdminLoginError(429, "Too many invalid codes. This sign-in is locked for 15 minutes.")
        return AdminTokenResponse(
            access_token="access-token-value",
            refresh_token="refresh-token-value",
            expires_in=3600,
            user={
                "id": str(uuid4()),
                "email": "ops@mindq.com",
                "full_name": "Ops Admin",
                "role": "admin",
                "corporate_id": str(uuid4()),
            },
        )

    monkeypatch.setattr("app.api.v1.admin_auth.start_admin_login", fake_start)
    monkeypatch.setattr("app.api.v1.admin_auth.verify_admin_otp", fake_verify)
    yield calls
    app.dependency_overrides.pop(get_db, None)
    admin_otp_limiter.reset()
    admin_otp_verify_limiter.reset()


@pytest.mark.asyncio
async def test_login_returns_otp_required_without_a_session(async_client, _routes):
    res = await async_client.post(
        LOGIN_URL, json={"email": "ops@mindq.com", "password": "correct-horse"}
    )
    assert res.status_code == 200
    body = res.json()
    assert body == {"status": "otp_required", "temp_token": "t" * 24}
    assert "access_token" not in body
    assert "password" not in body
    assert _routes == [("login", "ops@mindq.com", "correct-horse")]


@pytest.mark.asyncio
async def test_login_invalid_credentials_stay_generic(async_client, _routes):
    res = await async_client.post(
        LOGIN_URL, json={"email": "ops@mindq.com", "password": "wrong"}
    )
    assert res.status_code == 401
    assert res.json()["detail"] == "Invalid email or password"


@pytest.mark.asyncio
async def test_login_rate_limit_stops_otp_email_spam(async_client, _routes, monkeypatch):
    monkeypatch.setattr(admin_otp_limiter, "max_requests", 1)
    first = await async_client.post(
        LOGIN_URL, json={"email": "ops@mindq.com", "password": "correct-horse"}
    )
    second = await async_client.post(
        LOGIN_URL, json={"email": "ops@mindq.com", "password": "correct-horse"}
    )
    assert first.status_code == 200
    assert second.status_code == 429
    assert len(_routes) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "payload",
    [
        {"email": "not-an-email", "password": "secret"},
        {"email": "ops@mindq.com", "password": ""},
        {"email": "ops@mindq.com", "password": "secret", "otp": "123456"},
    ],
)
async def test_login_rejects_invalid_bodies(async_client, _routes, payload):
    res = await async_client.post(LOGIN_URL, json=payload)
    assert res.status_code == 422
    assert _routes == []


@pytest.mark.asyncio
async def test_verify_returns_the_admin_session_once(async_client, _routes):
    res = await async_client.post(
        VERIFY_URL, json={"temp_token": "t" * 24, "otp_code": "123456"}
    )
    assert res.status_code == 200
    body = res.json()
    assert body["access_token"] == "access-token-value"
    assert body["refresh_token"] == "refresh-token-value"
    assert body["token_type"] == "bearer"
    assert body["expires_in"] == 3600
    assert body["user"]["email"] == "ops@mindq.com"
    assert body["user"]["role"] == "admin"
    assert "otp_code" not in body
    assert _routes == [("verify", "t" * 24, "123456")]


@pytest.mark.asyncio
async def test_verify_lockout_is_429(async_client, _routes):
    res = await async_client.post(
        VERIFY_URL, json={"temp_token": "t" * 24, "otp_code": "000000"}
    )
    assert res.status_code == 429
    assert "15 minutes" in res.json()["detail"]


@pytest.mark.asyncio
@pytest.mark.parametrize("code", ["12345", "1234567", "abcdef", "12 456"])
async def test_verify_rejects_malformed_codes(async_client, _routes, code):
    res = await async_client.post(
        VERIFY_URL, json={"temp_token": "t" * 24, "otp_code": code}
    )
    assert res.status_code == 422
    assert _routes == []
