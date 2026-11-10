"""Tests for POST /api/v1/packages/{package_id}/candidates/bulk."""
from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.v1.packages import router
from app.auth import HRUserContext, get_current_ops_user
from app.database import get_db


@pytest.fixture
def corp_id():
    return uuid4()


@pytest.fixture
def package_id():
    return uuid4()


@pytest.fixture
def app():
    application = FastAPI()
    application.include_router(router, prefix="/api/v1/packages")

    async def _ops():
        return HRUserContext(
            user_id=uuid4(),
            corporate_id=uuid4(),
            email="ops@test.com",
            role="ops_admin",
        )

    async def _db():
        yield MagicMock()

    application.dependency_overrides[get_current_ops_user] = _ops
    application.dependency_overrides[get_db] = _db
    return application


def test_bulk_invite_queues_new_and_skips_existing(app, corp_id, package_id):
    client = TestClient(app)
    package = SimpleNamespace(
        id=package_id,
        title="Backend Pack",
        corporate_id=corp_id,
        status="published",
        close_time=None,
        is_active=True,
    )
    corporate = SimpleNamespace(id=corp_id, name="Acme Corp")

    new_candidate = SimpleNamespace(
        id=uuid4(),
        email="new@example.com",
        full_name="new",
        first_name=None,
        access_code="HM-AAAAAA-A",
        package_id=package_id,
        corporate_id=corp_id,
    )
    existing_candidate = SimpleNamespace(
        id=uuid4(),
        email="old@example.com",
        full_name="old",
        first_name=None,
        access_code="HM-BBBBBB-B",
        package_id=package_id,
        corporate_id=corp_id,
    )

    async def _invite(_session, *, email, package_id, corporate_id, full_name=None):
        del package_id, corporate_id, full_name
        if email == "old@example.com":
            return existing_candidate, False
        return new_candidate, True

    class _Result:
        def __init__(self, value):
            self._value = value

        def scalars(self):
            return SimpleNamespace(first=lambda: self._value)

        def scalar_one_or_none(self):
            return self._value

    db = MagicMock()

    async def _execute(stmt):
        del stmt
        # First execute loads package; second loads corporate.
        if not hasattr(_execute, "calls"):
            _execute.calls = 0
        _execute.calls += 1
        if _execute.calls == 1:
            return _Result(package)
        return _Result(corporate)

    db.execute = AsyncMock(side_effect=_execute)

    async def _db():
        yield db

    app.dependency_overrides[get_db] = _db

    with (
        patch("app.api.v1.packages.CandidateService.invite", new=_invite),
        patch(
            "app.api.v1.packages._dispatch_candidate_invite",
            new_callable=AsyncMock,
        ) as dispatch,
    ):
        res = client.post(
            f"/api/v1/packages/{package_id}/candidates/bulk",
            json={"emails": ["new@example.com", "old@example.com", "new@example.com"]},
        )

    assert res.status_code == 202
    body = res.json()
    assert body["invited_count"] == 1
    assert body["skipped_count"] == 1
    assert body["error_count"] == 0
    statuses = {row["email"]: row["status"] for row in body["results"]}
    assert statuses["new@example.com"] == "invited"
    assert statuses["old@example.com"] == "skipped"
    dispatch.assert_awaited_once()
