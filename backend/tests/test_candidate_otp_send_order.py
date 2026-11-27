"""P0-06: candidate OTP commits (releasing lock + connection) before SES."""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.services import candidate_otp
from app.services.candidate_otp import CandidateOtpError, request_candidate_otp


class _Result:
    def __init__(self, items=()):
        self._items = list(items)

    def scalars(self):
        return self

    def all(self):
        return self._items


class _OrderedDb:
    """Records commit / send / post-commit statements in call order."""

    def __init__(self, supersede_rows=()):
        self.events: list[str] = []
        self.added = []
        self._supersede_rows = list(supersede_rows)

    async def execute(self, stmt, *_a, **_k):
        if "commit" in self.events:
            self.events.append(f"execute:{str(stmt).split()[0]}")
            return _Result(self._supersede_rows)
        return _Result()  # advisory lock

    def add(self, row):
        self.added.append(row)

    async def commit(self):
        self.events.append("commit")

    async def rollback(self):
        self.events.append("rollback")


@pytest.fixture
def _gates(monkeypatch):
    monkeypatch.setattr(candidate_otp, "_validate_login_target", AsyncMock())
    monkeypatch.setattr(
        candidate_otp, "_find_existing_login_candidate", AsyncMock(return_value=None)
    )
    monkeypatch.setattr(candidate_otp, "_is_locked", AsyncMock(return_value=False))
    monkeypatch.setattr(candidate_otp, "_recent_sends", AsyncMock(return_value=[]))


@pytest.mark.asyncio
async def test_candidate_otp_commits_before_send_then_supersedes(monkeypatch, _gates):
    old = SimpleNamespace(locked_until=None, consumed_at=None, otp_hash="h")
    db = _OrderedDb(supersede_rows=[old])

    async def _send(_email, _otp):
        db.events.append("send")

    monkeypatch.setattr(candidate_otp, "send_candidate_otp_email", _send)
    res = await request_candidate_otp(db, "HM-ABC", "ada@example.com")
    assert res.status == "otp_required"
    assert db.events == ["commit", "send", "execute:SELECT", "commit"]
    assert old.consumed_at is not None and old.otp_hash == ""


@pytest.mark.asyncio
async def test_candidate_otp_send_failure_discards_challenge(monkeypatch, _gates):
    db = _OrderedDb()

    async def _send(_email, _otp):
        db.events.append("send")
        raise RuntimeError("SES throttled")

    monkeypatch.setattr(candidate_otp, "send_candidate_otp_email", _send)
    with pytest.raises(CandidateOtpError) as exc:
        await request_candidate_otp(db, "HM-ABC", "ada@example.com")
    assert exc.value.status_code == 503
    assert db.events == ["commit", "send", "execute:DELETE", "commit"]


def test_ses_client_has_short_timeouts():
    from app.services.email import SES_CLIENT_CONFIG

    assert SES_CLIENT_CONFIG.connect_timeout == 3
    assert SES_CLIENT_CONFIG.read_timeout == 5
    assert SES_CLIENT_CONFIG.retries == {"max_attempts": 2, "mode": "standard"}
