"""HR/client OTP: HMAC storage, SES send path, backend client JWT at verify."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import jwt
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.auth import get_current_client_user
from app.config import settings
from app.database import get_db
from app.services.admin_otp import apply_otp_attempt, hash_otp
from app.services.hr_otp import (
    HR_OTP_AUDIENCE,
    HrOtpError,
    decode_hr_otp_token,
    issue_hr_otp_token,
    request_hr_otp,
    verify_hr_challenge,
)

EMAIL = "hr@acme.test"


def _challenge(user_id, code: str = "123456"):
    challenge_id = uuid4()
    now = datetime.now(timezone.utc)
    row = SimpleNamespace(
        id=challenge_id,
        user_id=user_id,
        email=EMAIL,
        otp_hash=hash_otp(challenge_id, code),
        expires_at=now + timedelta(minutes=5),
        attempt_count=0,
        locked_until=None,
        consumed_at=None,
        created_at=now,
    )
    return row, now


def _membership(user_id, corporate_id, role: str = "hr"):
    return SimpleNamespace(
        user_id=user_id, corporate_id=corporate_id, full_name="Harriet HR", role=role
    )


def _corporate(
    corporate_id, *, allowed_hr_emails=None, contact_email=None, is_active=True
):
    return SimpleNamespace(
        id=corporate_id,
        name="Acme",
        logo_url=None,
        contact_email=contact_email,
        allowed_hr_emails=[EMAIL] if allowed_hr_emails is None else allowed_hr_emails,
        is_active=is_active,
    )


class _Result:
    def __init__(self, scalar=None, scalars=None, first=None):
        self._scalar = scalar
        self._scalars = scalars or []
        self._first = first

    def scalar_one_or_none(self):
        return self._scalar

    def scalars(self):
        return SimpleNamespace(all=lambda: list(self._scalars))

    def first(self):
        return self._first


class _FakeDb:
    """Queue-backed stand-in: each execute() pops the next prepared result."""

    def __init__(self, results):
        self._results = list(results)
        self.added = []
        self.committed = False

    async def execute(self, *_args, **_kwargs):
        return self._results.pop(0)

    def add(self, row):
        self.added.append(row)

    async def flush(self):
        return None

    async def commit(self):
        self.committed = True

    async def rollback(self):
        return None


def test_challenge_model_matches_migration_schema():
    from app.models.hr_login_challenge import HrLoginChallenge

    table = HrLoginChallenge.__table__
    assert table.name == "hr_login_challenges"
    assert set(table.columns.keys()) == {
        "id",
        "user_id",
        "email",
        "otp_hash",
        "expires_at",
        "attempt_count",
        "locked_until",
        "consumed_at",
        "created_at",
    }
    assert table.c.locked_until.nullable is True
    assert table.c.user_id.foreign_keys


def test_temp_token_round_trip_binds_challenge_user_and_email():
    challenge_id, user_id = uuid4(), uuid4()
    token = issue_hr_otp_token(challenge_id, user_id, EMAIL)
    assert decode_hr_otp_token(token) == (challenge_id, user_id, EMAIL)


def test_temp_token_rejects_wrong_type():
    now = datetime.now(timezone.utc)
    forged = jwt.encode(
        {
            "sub": str(uuid4()),
            "challenge_id": str(uuid4()),
            "email": EMAIL,
            "typ": "client",
            "aud": HR_OTP_AUDIENCE,
            "iat": now,
            "exp": now + timedelta(minutes=5),
        },
        settings.SECRET_KEY,
        algorithm="HS256",
    )
    with pytest.raises(jwt.PyJWTError):
        decode_hr_otp_token(forged)


def test_three_invalid_codes_lock_and_burn_the_code():
    row, now = _challenge(uuid4())
    assert apply_otp_attempt(row, "000001", now) == "rejected"
    assert apply_otp_attempt(row, "000002", now) == "rejected"
    assert apply_otp_attempt(row, "000003", now) == "locked"
    assert row.otp_hash == ""


@pytest.mark.asyncio
async def test_request_rejects_unregistered_email_without_touching_db():
    # No Auth user and no company whitelist match → still 403.
    db = _FakeDb([_Result(scalars=[])])
    with patch("app.services.hr_otp.find_auth_user_id_by_email", return_value=None):
        with pytest.raises(HrOtpError) as exc:
            await request_hr_otp(db, "  Ghost@Acme.Test ")
    assert exc.value.status_code == 403
    assert "not registered" in exc.value.detail
    assert db.added == []


@pytest.mark.asyncio
async def test_request_provisions_auth_for_whitelist_only_email():
    """Admin-added allowed_hr_emails without Invite HR still get OTP access."""
    secondary = "mohamed@happymind.lk"
    user_id, corporate_id = uuid4(), uuid4()
    corp = _corporate(
        corporate_id,
        contact_email="hr@acme.test",
        allowed_hr_emails=["hr@acme.test", secondary],
    )
    membership = _membership(user_id, corporate_id)
    db = _FakeDb(
        [
            _Result(scalars=[corp]),  # whitelist company lookup
            _Result(scalar=membership),  # reload after upsert
            _Result(),  # advisory lock
            _Result(first=None),
            _Result(scalars=[]),
            _Result(scalars=[]),
        ]
    )
    sent: dict = {}

    async def _send(email, otp):
        sent["email"] = email
        sent["otp"] = otp

    with (
        patch("app.services.hr_otp.find_auth_user_id_by_email", return_value=None),
        patch("app.services.hr_otp.ensure_auth_user", return_value=user_id) as ensure,
        patch(
            "app.services.hr_otp.upsert_hr_membership", new=AsyncMock()
        ) as upsert,
        patch("app.services.hr_otp.send_hr_otp_email", new=_send),
    ):
        response = await request_hr_otp(db, f"  {secondary.upper()} ")

    assert response.status == "otp_required"
    ensure.assert_called_once_with(secondary)
    upsert.assert_awaited_once()
    assert sent["email"] == secondary
    _, token_user, token_email = decode_hr_otp_token(response.temp_token)
    assert token_user == user_id
    assert token_email == secondary
    assert db.committed is True


@pytest.mark.asyncio
async def test_request_rejects_ops_account():
    user_id = uuid4()
    db = _FakeDb([_Result(scalar=_membership(user_id, uuid4(), role="admin"))])
    with patch("app.services.hr_otp.find_auth_user_id_by_email", return_value=user_id):
        with pytest.raises(HrOtpError) as exc:
            await request_hr_otp(db, EMAIL)
    assert exc.value.status_code == 403
    assert "admin portal" in exc.value.detail


@pytest.mark.asyncio
async def test_request_sends_ses_code_and_returns_temp_token():
    user_id, corporate_id = uuid4(), uuid4()
    db = _FakeDb(
        [
            _Result(scalar=_membership(user_id, corporate_id)),
            _Result(scalar=_corporate(corporate_id)),
            _Result(),
            _Result(first=None),
            _Result(scalars=[]),
            _Result(scalars=[]),
        ]
    )
    sent: dict = {}

    async def _send(email, otp):
        sent["email"] = email
        sent["otp"] = otp

    with (
        patch("app.services.hr_otp.find_auth_user_id_by_email", return_value=user_id),
        patch("app.services.hr_otp.send_hr_otp_email", new=_send),
    ):
        response = await request_hr_otp(db, "  HR@Acme.Test ")

    assert response.status == "otp_required"
    # Recipient is cleaned/normalized before SES dispatch.
    assert sent["email"] == EMAIL
    assert len(sent["otp"]) == 6 and sent["otp"].isdigit()
    challenge_id, token_user, token_email = decode_hr_otp_token(response.temp_token)
    assert token_user == user_id
    assert token_email == EMAIL
    (row,) = db.added
    assert row.id == challenge_id
    assert row.otp_hash != sent["otp"]
    assert db.committed is True


@pytest.mark.asyncio
async def test_request_rejects_email_not_on_company_whitelist():
    user_id, corporate_id = uuid4(), uuid4()
    db = _FakeDb(
        [
            _Result(scalar=_membership(user_id, corporate_id)),
            _Result(scalar=_corporate(corporate_id, allowed_hr_emails=["other@acme.test"])),
            _Result(scalars=[]),  # no active whitelist rebind target
        ]
    )
    with patch("app.services.hr_otp.find_auth_user_id_by_email", return_value=user_id):
        with pytest.raises(HrOtpError) as exc:
            await request_hr_otp(db, EMAIL)
    assert exc.value.status_code == 403
    assert "not registered" in exc.value.detail
    assert db.added == []


@pytest.mark.asyncio
async def test_request_accepts_secondary_whitelisted_email():
    """Secondary HR emails on allowed_hr_emails can request OTP."""
    secondary = "mohamed@happymind.lk"
    user_id, corporate_id = uuid4(), uuid4()
    db = _FakeDb(
        [
            _Result(scalar=_membership(user_id, corporate_id)),
            _Result(
                scalar=_corporate(
                    corporate_id,
                    contact_email="hr@acme.test",
                    allowed_hr_emails=["hr@acme.test", secondary],
                )
            ),
            _Result(),
            _Result(first=None),
            _Result(scalars=[]),
            _Result(scalars=[]),
        ]
    )
    sent: dict = {}

    async def _send(email, otp):
        sent["email"] = email
        sent["otp"] = otp

    with (
        patch("app.services.hr_otp.find_auth_user_id_by_email", return_value=user_id),
        patch("app.services.hr_otp.send_hr_otp_email", new=_send),
    ):
        response = await request_hr_otp(db, f"  {secondary.upper()} ")

    assert response.status == "otp_required"
    assert sent["email"] == secondary
    _, token_user, token_email = decode_hr_otp_token(response.temp_token)
    assert token_user == user_id
    assert token_email == secondary
    assert db.committed is True


@pytest.mark.asyncio
async def test_request_accepts_contact_email_when_not_in_allowed_list():
    """Primary contact_email grants access even if allowed_hr_emails is empty."""
    user_id, corporate_id = uuid4(), uuid4()
    db = _FakeDb(
        [
            _Result(scalar=_membership(user_id, corporate_id)),
            _Result(
                scalar=_corporate(
                    corporate_id, contact_email=EMAIL, allowed_hr_emails=[]
                )
            ),
            _Result(),
            _Result(first=None),
            _Result(scalars=[]),
            _Result(scalars=[]),
        ]
    )
    sent: dict = {}

    async def _send(email, otp):
        sent["email"] = email

    with (
        patch("app.services.hr_otp.find_auth_user_id_by_email", return_value=user_id),
        patch("app.services.hr_otp.send_hr_otp_email", new=_send),
    ):
        response = await request_hr_otp(db, "  HR@Acme.Test ")

    assert response.status == "otp_required"
    assert sent["email"] == EMAIL
    assert db.committed is True


@pytest.mark.asyncio
async def test_request_accepts_mixed_case_whitelist_entry():
    """Stored whitelist casing must not block a normalized login email."""
    user_id, corporate_id = uuid4(), uuid4()
    db = _FakeDb(
        [
            _Result(scalar=_membership(user_id, corporate_id)),
            _Result(
                scalar=_corporate(
                    corporate_id, allowed_hr_emails=["  HR@Acme.Test "]
                )
            ),
            _Result(),
            _Result(first=None),
            _Result(scalars=[]),
            _Result(scalars=[]),
        ]
    )

    with (
        patch("app.services.hr_otp.find_auth_user_id_by_email", return_value=user_id),
        patch("app.services.hr_otp.send_hr_otp_email", new=AsyncMock()),
    ):
        response = await request_hr_otp(db, EMAIL)

    assert response.status == "otp_required"
    assert db.committed is True


@pytest.mark.asyncio
async def test_request_rejects_inactive_company():
    user_id, corporate_id = uuid4(), uuid4()
    db = _FakeDb(
        [
            _Result(scalar=_membership(user_id, corporate_id)),
            _Result(scalar=_corporate(corporate_id, is_active=False)),
            _Result(scalars=[]),  # no active whitelist rebind target
        ]
    )
    with patch("app.services.hr_otp.find_auth_user_id_by_email", return_value=user_id):
        with pytest.raises(HrOtpError) as exc:
            await request_hr_otp(db, EMAIL)
    assert exc.value.status_code == 403
    assert db.added == []


@pytest.mark.asyncio
async def test_request_rebinds_from_inactive_corp_to_active_whitelist():
    """Stale hr_users on a deactivated tenant can re-home via active whitelist."""
    user_id, stale_corp_id, active_corp_id = uuid4(), uuid4(), uuid4()
    active = _corporate(
        active_corp_id,
        contact_email="owner@acme.test",
        allowed_hr_emails=[EMAIL],
        is_active=True,
    )
    rebound = _membership(user_id, active_corp_id)
    db = _FakeDb(
        [
            _Result(scalar=_membership(user_id, stale_corp_id)),
            _Result(scalar=_corporate(stale_corp_id, is_active=False)),
            _Result(scalars=[active]),  # active whitelist lookup
            _Result(scalar=rebound),  # membership after upsert
            _Result(),  # advisory lock
            _Result(first=None),
            _Result(scalars=[]),
            _Result(scalars=[]),
        ]
    )
    sent: dict = {}

    async def _send(email, otp):
        sent["email"] = email
        sent["otp"] = otp

    with (
        patch("app.services.hr_otp.find_auth_user_id_by_email", return_value=user_id),
        patch("app.services.hr_otp.upsert_hr_membership", new=AsyncMock()) as upsert,
        patch("app.services.hr_otp.send_hr_otp_email", new=_send),
    ):
        response = await request_hr_otp(db, EMAIL)

    assert response.status == "otp_required"
    upsert.assert_awaited_once()
    assert upsert.await_args.kwargs["corporate_id"] == active_corp_id
    assert sent["email"] == EMAIL
    _, token_user, token_email = decode_hr_otp_token(response.temp_token)
    assert token_user == user_id
    assert token_email == EMAIL
    assert db.committed is True


@pytest.mark.asyncio
async def test_request_mail_failure_rolls_back_to_503():
    user_id, corporate_id = uuid4(), uuid4()
    db = _FakeDb(
        [
            _Result(scalar=_membership(user_id, corporate_id)),
            _Result(scalar=_corporate(corporate_id)),
            _Result(),
            _Result(first=None),
            _Result(scalars=[]),
            _Result(scalars=[]),
        ]
    )

    async def _send(_email, _otp):
        raise RuntimeError("SES rejected")

    with (
        patch("app.services.hr_otp.find_auth_user_id_by_email", return_value=user_id),
        patch("app.services.hr_otp.send_hr_otp_email", new=_send),
    ):
        with pytest.raises(HrOtpError) as exc:
            await request_hr_otp(db, EMAIL)
    assert exc.value.status_code == 503
    assert db.committed is False


def _verify_db(row, user_id, corporate_id):
    return _FakeDb(
        [
            _Result(scalar=row),
            _Result(scalar=_membership(user_id, corporate_id)),
            _Result(scalar=_corporate(corporate_id)),
        ]
    )


@pytest.mark.asyncio
async def test_verify_accepts_code_and_mints_backend_client_jwt():
    user_id, corporate_id = uuid4(), uuid4()
    row, _now = _challenge(user_id)
    token = issue_hr_otp_token(row.id, user_id, EMAIL)
    db = _verify_db(row, user_id, corporate_id)

    response = await verify_hr_challenge(
        db, temp_token=token, otp_code="123456", email="HR@Acme.Test"
    )

    assert row.consumed_at is not None
    assert db.committed is True
    assert response.corporate.id == corporate_id
    assert response.user.email == EMAIL
    assert response.user.role == "hr"
    ctx = await get_current_client_user(authorization=f"Bearer {response.access_token}")
    assert ctx.user_id == user_id
    assert ctx.corporate_id == corporate_id


@pytest.mark.asyncio
async def test_verify_rejects_when_revoked_from_whitelist_after_send():
    user_id, corporate_id = uuid4(), uuid4()
    row, _now = _challenge(user_id)
    token = issue_hr_otp_token(row.id, user_id, EMAIL)
    db = _FakeDb(
        [
            _Result(scalar=row),
            _Result(scalar=_membership(user_id, corporate_id)),
            _Result(scalar=_corporate(corporate_id, allowed_hr_emails=[])),
        ]
    )
    with pytest.raises(HrOtpError) as exc:
        await verify_hr_challenge(
            db, temp_token=token, otp_code="123456", email=EMAIL
        )
    assert exc.value.status_code == 403
    assert row.consumed_at is not None


@pytest.mark.asyncio
async def test_verify_rejects_code_for_a_different_email():
    user_id, corporate_id = uuid4(), uuid4()
    row, _now = _challenge(user_id)
    token = issue_hr_otp_token(row.id, user_id, EMAIL)
    with pytest.raises(HrOtpError) as exc:
        await verify_hr_challenge(
            _verify_db(row, user_id, corporate_id),
            temp_token=token,
            otp_code="123456",
            email="mallory@acme.test",
        )
    assert exc.value.status_code == 401


@pytest.mark.asyncio
async def test_verify_rejects_wrong_code_and_counts_attempt():
    user_id, corporate_id = uuid4(), uuid4()
    row, _now = _challenge(user_id)
    token = issue_hr_otp_token(row.id, user_id, EMAIL)
    with pytest.raises(HrOtpError) as exc:
        await verify_hr_challenge(
            _verify_db(row, user_id, corporate_id),
            temp_token=token,
            otp_code="000000",
            email=EMAIL,
        )
    assert exc.value.status_code == 401
    assert row.attempt_count == 1


def test_hr_auth_routes_mount_at_v1_paths():
    from app.main import app

    paths = app.openapi()["paths"]
    assert "post" in paths["/api/v1/hr/auth/otp/send"]
    assert "post" in paths["/api/v1/hr/auth/otp/verify"]


@pytest.fixture
def _no_rate_limit():
    with patch("app.api.v1.hr_auth.enforce_rate_limit"):
        yield


def test_send_route_returns_challenge_shape(_no_rate_limit):
    from app.api.v1.hr_auth import router as hr_router
    from app.schemas.hr_auth import HrOtpChallengeResponse

    application = FastAPI()
    application.include_router(hr_router, prefix="/hr/auth")

    async def _db():
        yield AsyncMock()

    application.dependency_overrides[get_db] = _db
    challenge = HrOtpChallengeResponse(status="otp_required", temp_token="t" * 24)
    with patch("app.api.v1.hr_auth.request_hr_otp", new=AsyncMock(return_value=challenge)):
        res = TestClient(application).post(
            "/hr/auth/otp/send", json={"email": "hr@acme.example.com"}
        )
    assert res.status_code == 200
    assert res.json() == {"status": "otp_required", "temp_token": "t" * 24}
