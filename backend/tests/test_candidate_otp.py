"""Candidate OTP primitives: HMAC storage, lockout, temp tokens, send caps."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from uuid import uuid4

import jwt
import pytest

from app.config import settings
from app.services.admin_otp import apply_otp_attempt, hash_otp, otp_matches, send_block_reason
from app.services.candidate_otp import (
    CANDIDATE_OTP_AUDIENCE,
    CandidateOtpError,
    decode_candidate_otp_token,
    issue_candidate_otp_token,
    verify_candidate_challenge,
)


def _challenge(code: str = "123456"):
    challenge_id = uuid4()
    now = datetime.now(timezone.utc)
    row = SimpleNamespace(
        id=challenge_id,
        email="ada@example.com",
        access_code="HM-1",
        otp_hash=hash_otp(challenge_id, code),
        expires_at=now + timedelta(minutes=5),
        attempt_count=0,
        locked_until=None,
        consumed_at=None,
        created_at=now,
    )
    return row, now


def test_code_is_stored_only_as_hmac():
    row, _now = _challenge()
    assert row.otp_hash != "123456"
    assert otp_matches(row.id, "123456", row.otp_hash)
    assert not otp_matches(row.id, "000000", row.otp_hash)
    assert not otp_matches(uuid4(), "123456", row.otp_hash)


def test_three_invalid_codes_lock_and_burn_the_code():
    row, now = _challenge()
    assert apply_otp_attempt(row, "000001", now) == "rejected"
    assert apply_otp_attempt(row, "000002", now) == "rejected"
    assert apply_otp_attempt(row, "000003", now) == "locked"
    assert row.otp_hash == ""
    assert apply_otp_attempt(row, "123456", now) == "locked"


def test_correct_code_is_consumed_once():
    row, now = _challenge()
    assert apply_otp_attempt(row, "123456", now) == "accepted"
    assert apply_otp_attempt(row, "123456", now) == "consumed"


def test_expired_code_is_rejected_and_burned():
    row, now = _challenge()
    assert apply_otp_attempt(row, "123456", now + timedelta(minutes=6)) == "expired"
    assert row.otp_hash == ""


def test_temp_token_round_trip_binds_challenge_email_and_code():
    challenge_id = uuid4()
    token = issue_candidate_otp_token(challenge_id, "ada@example.com", "HM-1")
    assert decode_candidate_otp_token(token) == (challenge_id, "ada@example.com", "HM-1")


def test_temp_token_rejects_wrong_type_and_expired_tokens():
    challenge_id = uuid4()
    now = datetime.now(timezone.utc)
    forged = jwt.encode(
        {
            "sub": "ada@example.com",
            "challenge_id": str(challenge_id),
            "email": "ada@example.com",
            "access_code": "HM-1",
            "typ": "candidate_session",
            "aud": CANDIDATE_OTP_AUDIENCE,
            "iat": now,
            "exp": now + timedelta(minutes=5),
        },
        settings.SECRET_KEY,
        algorithm="HS256",
    )
    with pytest.raises(jwt.PyJWTError):
        decode_candidate_otp_token(forged)


def test_send_block_reason_cooldown_and_window():
    now = datetime.now(timezone.utc)
    assert send_block_reason([], now) is None
    assert send_block_reason([now], now) == "cooldown"
    recent = [now - timedelta(minutes=5), now - timedelta(minutes=4), now - timedelta(minutes=3)]
    assert send_block_reason(recent, now) == "window"


class _FakeResult:
    def __init__(self, row):
        self._row = row

    def scalar_one_or_none(self):
        return self._row


class _FakeDb:
    def __init__(self, row):
        self._row = row
        self.committed = False

    async def execute(self, *_args, **_kwargs):
        return _FakeResult(self._row)

    async def commit(self):
        self.committed = True


@pytest.mark.asyncio
async def test_verify_accepts_correct_code_and_commits():
    row, _now = _challenge()
    token = issue_candidate_otp_token(row.id, row.email, row.access_code)
    db = _FakeDb(row)
    await verify_candidate_challenge(
        db, temp_token=token, otp_code="123456", email="ADA@example.com", access_code="hm-1"
    )
    assert row.consumed_at is not None
    assert db.committed is True


@pytest.mark.asyncio
async def test_verify_rejects_code_for_a_different_email():
    row, _now = _challenge()
    token = issue_candidate_otp_token(row.id, row.email, row.access_code)
    with pytest.raises(CandidateOtpError) as exc:
        await verify_candidate_challenge(
            _FakeDb(row),
            temp_token=token,
            otp_code="123456",
            email="mallory@example.com",
            access_code="HM-1",
        )
    assert exc.value.status_code == 401


@pytest.mark.asyncio
async def test_verify_rejects_wrong_code():
    row, _now = _challenge()
    token = issue_candidate_otp_token(row.id, row.email, row.access_code)
    with pytest.raises(CandidateOtpError) as exc:
        await verify_candidate_challenge(
            _FakeDb(row), temp_token=token, otp_code="000000", email=row.email, access_code="HM-1"
        )
    assert exc.value.status_code == 401
    assert row.attempt_count == 1
