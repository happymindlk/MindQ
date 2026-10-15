"""Tests for POST /api/candidates/invite."""
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


@pytest.fixture
def corp_id():
    return uuid4()


@pytest.fixture
def package_id():
    return uuid4()


@pytest.fixture
def app(corp_id):
    application = FastAPI()
    application.include_router(router, prefix="/api/candidates")

    async def _hr():
        return HRUserContext(user_id=uuid4(), corporate_id=corp_id, email="hr@test.com")

    async def _db():
        yield MagicMock()

    application.dependency_overrides[get_current_hr_user] = _hr
    application.dependency_overrides[get_db] = _db
    return application


def test_invite_rejects_other_tenant(app, corp_id, package_id):
    client = TestClient(app)
    res = client.post(
        "/api/candidates/invite",
        json={
            "candidate_email": "pat@example.com",
            "package_id": str(package_id),
            "corporate_id": str(uuid4()),
        },
    )
    assert res.status_code == 403


def test_invite_sends_resend_and_returns_pending(app, corp_id, package_id):
    client = TestClient(app)
    candidate_id = uuid4()
    access = str(uuid4())
    candidate = SimpleNamespace(
        id=candidate_id,
        email="pat@example.com",
        full_name="pat",
        package_id=package_id,
        corporate_id=corp_id,
        access_code=access,
    )

    async def _invite(*_args, **_kwargs):
        return candidate, True

    db = MagicMock()

    class _Result:
        def scalars(self):
            return SimpleNamespace(first=lambda: SimpleNamespace(
                title="Backend Pack",
                corporate_id=corp_id,
                status="published",
            ))

        def scalar_one_or_none(self):
            return SimpleNamespace(name="Acme Corp")

    db.execute = AsyncMock(return_value=_Result())

    async def _db():
        yield db

    app.dependency_overrides[get_db] = _db

    with (
        patch("app.api.v1.invites.settings") as settings,
        patch("app.api.v1.invites.CandidateService.invite", new=_invite),
        patch(
            "app.api.v1.invites.EmailService.send_candidate_invite_email",
            new_callable=AsyncMock,
            return_value=True,
        ) as send_mail,
    ):
        settings.resend_configured = True
        res = client.post(
            "/api/candidates/invite",
            json={
                "candidate_email": "pat@example.com",
                "package_id": str(package_id),
                "corporate_id": str(corp_id),
            },
        )

    assert res.status_code == 200
    body = res.json()
    assert body["status"] == "pending"
    assert body["access_code"] == access
    assert body["candidate_email"] == "pat@example.com"
    send_mail.assert_awaited_once()
    assert send_mail.await_args.kwargs.get("raise_on_error") is True


def test_invite_requires_resend(app, corp_id, package_id):
    client = TestClient(app)
    with patch("app.api.v1.invites.settings") as settings:
        settings.resend_configured = False
        res = client.post(
            "/api/candidates/invite",
            json={
                "candidate_email": "pat@example.com",
                "package_id": str(package_id),
                "corporate_id": str(corp_id),
            },
        )
    assert res.status_code == 503
