"""Invites and portal links must share ``package.access_code``."""
from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.v1.invites import router
from app.auth import HRUserContext, get_current_hr_user
from app.database import get_db
from app.schemas.candidate import CandidateAuthOtpVerifyRequest
from app.services.candidate_service import CandidateService


class _ScalarResult:
    def __init__(self, value):
        self._value = value

    def scalars(self):
        return self

    def first(self):
        return self._value

    def scalar_one_or_none(self):
        return self._value


class _InviteSession:
    """Minimal async session for ``CandidateService.invite``."""

    def __init__(self, package, existing=None):
        self.package = package
        self.existing = existing
        self.added = []
        self._calls = 0

    async def execute(self, _stmt):
        self._calls += 1
        # 1: load package; 2: existing-by-email lookup; IntegrityError path unused.
        if self._calls == 1:
            return _ScalarResult(self.package)
        return _ScalarResult(self.existing)

    def add(self, obj):
        self.added.append(obj)

    async def commit(self):
        return None

    async def refresh(self, obj):
        if getattr(obj, "id", None) is None:
            obj.id = uuid4()


class _LegacyLoginSession:
    """package miss → candidate-by-code → package-by-id."""

    def __init__(self, invited, invited_package):
        self.invited = invited
        self.invited_package = invited_package
        self._calls = 0
        self.added = []

    async def execute(self, _stmt):
        self._calls += 1
        if self._calls == 1:
            return _ScalarResult(None)
        if self._calls == 2:
            return _ScalarResult(self.invited)
        return _ScalarResult(self.invited_package)

    def add(self, obj):
        self.added.append(obj)

    async def commit(self):
        return None

    async def refresh(self, obj):
        return None


@pytest.mark.asyncio
async def test_invite_assigns_package_access_code_not_minted_pin():
    corp_id = uuid4()
    package = SimpleNamespace(
        id=uuid4(),
        corporate_id=corp_id,
        access_code="HM-PKG001-A",
        is_active=True,
    )
    session = _InviteSession(package=package)

    candidate, created = await CandidateService.invite(
        session,
        email="pat@example.com",
        package_id=package.id,
        corporate_id=corp_id,
        full_name="Pat Candidate",
    )

    assert created is True
    assert candidate.access_code == package.access_code == "HM-PKG001-A"
    assert len(session.added) == 1


@pytest.mark.asyncio
async def test_login_still_resolves_legacy_candidate_access_code():
    corp_id = uuid4()
    pkg_id = uuid4()
    invited = SimpleNamespace(
        id=uuid4(),
        corporate_id=corp_id,
        package_id=pkg_id,
        email="legacy@example.com",
        access_code="HM-LEGACY-C",
        full_name="Legacy User",
        first_name="Legacy",
        logged_in_at=None,
        terms_accepted_at=None,
    )
    invited_package = SimpleNamespace(
        id=pkg_id,
        corporate_id=corp_id,
        access_code="HM-PKG999-A",
        is_active=True,
        open_time=None,
        close_time=None,
    )
    session = _LegacyLoginSession(invited, invited_package)

    async def _fake_window(_session, package, candidate):
        del _session, package, candidate

    login = CandidateAuthOtpVerifyRequest(
        first_name="Legacy",
        full_name="Legacy User",
        email="legacy@example.com",
        access_code="HM-LEGACY-C",
        temp_token="t" * 24,
        otp_code="123456",
        terms_accepted=True,
    )

    with patch.object(CandidateService, "_ensure_login_window", new=_fake_window):
        candidate, is_new = await CandidateService.login(session, login)

    assert is_new is False
    assert candidate.access_code == "HM-LEGACY-C"
    assert candidate.email == "legacy@example.com"


@pytest.fixture
def corp_id():
    return uuid4()


@pytest.fixture
def package_id():
    return uuid4()


@pytest.fixture
def invite_app(corp_id):
    application = FastAPI()
    application.include_router(router, prefix="/api/candidates")

    async def _hr():
        return HRUserContext(user_id=uuid4(), corporate_id=corp_id, email="hr@test.com")

    async def _db():
        yield MagicMock()

    application.dependency_overrides[get_current_hr_user] = _hr
    application.dependency_overrides[get_db] = _db
    return application


def test_invite_api_enqueues_and_returns_package_access_code(
    invite_app, corp_id, package_id
):
    client = TestClient(invite_app)
    package_code = "HM-SHARED-1"
    candidate = SimpleNamespace(
        id=uuid4(),
        email="pat@example.com",
        full_name="pat",
        first_name=None,
        package_id=package_id,
        corporate_id=corp_id,
        # Legacy-shaped row still stores a distinct pin; API must prefer package.
        access_code="HM-OLD-PIN",
    )

    async def _invite(*_args, **_kwargs):
        return candidate, True

    db = MagicMock()

    class _Result:
        def scalars(self):
            return SimpleNamespace(
                first=lambda: SimpleNamespace(
                    title="Backend Pack",
                    corporate_id=corp_id,
                    status="published",
                    access_code=package_code,
                    close_time=None,
                )
            )

        def scalar_one_or_none(self):
            return SimpleNamespace(name="Acme Corp")

    db.execute = AsyncMock(return_value=_Result())

    async def _db():
        yield db

    invite_app.dependency_overrides[get_db] = _db
    captured: dict = {}

    async def _enqueue(**kwargs):
        captured.update(kwargs)

    with (
        patch("app.api.v1.invites.CandidateService.invite", new=_invite),
        patch("app.api.v1.invites.enqueue_candidate_invite", new=_enqueue),
    ):
        res = client.post(
            "/api/candidates/invite",
            json={
                "candidate_email": "pat@example.com",
                "package_id": str(package_id),
                "corporate_id": str(corp_id),
            },
        )

    assert res.status_code == 202
    body = res.json()
    assert body["access_code"] == package_code
    assert captured["access_code"] == package_code
