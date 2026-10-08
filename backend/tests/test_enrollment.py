"""Invite-only package enrollment tests."""
from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.schemas.candidate import CandidateLogin, strip_answer_keys
from app.services.candidate_service import CandidateService


class _ScalarResult:
    def __init__(self, value):
        self._value = value

    def scalars(self):
        return self

    def first(self):
        return self._value


class _FakeSession:
    def __init__(self, package, candidate=None):
        self.package = package
        self.candidate = candidate
        self.added = []
        self.commits = 0

    async def execute(self, _stmt):
        # First call resolves package; second resolves candidate by email.
        if not hasattr(self, "_calls"):
            self._calls = 0
        self._calls += 1
        if self._calls == 1:
            return _ScalarResult(self.package)
        return _ScalarResult(self.candidate)

    def add(self, obj):
        self.added.append(obj)

    async def commit(self):
        self.commits += 1

    async def refresh(self, obj):
        if getattr(obj, "id", None) is None:
            obj.id = uuid4()


@pytest.mark.asyncio
async def test_package_code_rejects_uninvited_when_enrollment_closed():
    package = SimpleNamespace(
        id=uuid4(),
        corporate_id=uuid4(),
        access_code="HM-TEST1-A",
        is_active=True,
        allow_open_enrollment=False,
    )
    session = _FakeSession(package=package, candidate=None)
    login = CandidateLogin(
        first_name="Ada",
        full_name="Ada Lovelace",
        email="ada@example.com",
        access_code="HM-TEST1-A",
    )
    with pytest.raises(ValueError, match="invitation is required"):
        await CandidateService.login(session, login)
    assert session.added == []


@pytest.mark.asyncio
async def test_package_code_open_enrollment_creates_candidate():
    package = SimpleNamespace(
        id=uuid4(),
        corporate_id=uuid4(),
        access_code="HM-OPEN1-A",
        is_active=True,
        allow_open_enrollment=True,
    )
    session = _FakeSession(package=package, candidate=None)
    login = CandidateLogin(
        first_name="Ada",
        full_name="Ada Lovelace",
        email="ada@example.com",
        access_code="HM-OPEN1-A",
    )
    candidate, is_new = await CandidateService.login(session, login)
    assert is_new is True
    assert candidate.email == "ada@example.com"
    assert candidate.first_name == "Ada"
    assert candidate.full_name == "Ada Lovelace"
    assert len(session.added) == 1


def test_strip_answer_keys_removes_correct_answer_or_rubric():
    source = [
        {
            "id": "q1",
            "text": "Explain CAP",
            "type": "open_ended",
            "correct_answer_or_rubric": "mentions partitions",
            "scoring_key": "secret",
        }
    ]
    cleaned = strip_answer_keys(source)
    assert "correct_answer_or_rubric" not in cleaned[0]
    assert "scoring_key" not in cleaned[0]
    assert source[0]["correct_answer_or_rubric"] == "mentions partitions"
