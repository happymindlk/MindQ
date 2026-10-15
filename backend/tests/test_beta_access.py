"""Tests for gated beta access request endpoint."""
from __future__ import annotations

from uuid import uuid4
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.v1.beta_access import router
from app.auth import SupabaseUserContext, get_current_supabase_user
from app.database import get_db


@pytest.fixture
def user_id():
    return uuid4()


@pytest.fixture
def app(user_id):
    application = FastAPI()
    application.include_router(router)

    async def _user():
        return SupabaseUserContext(
            user_id=user_id,
            email="hr@acme.test",
            corporate_id=None,
        )

    async def _db():
        yield MagicMock()

    application.dependency_overrides[get_current_supabase_user] = _user
    application.dependency_overrides[get_db] = _db
    return application


def test_request_beta_access_sends_email(app, user_id):
    client = TestClient(app)
    with (
        patch("app.api.v1.beta_access.settings") as settings,
        patch(
            "app.api.v1.beta_access.send_transactional_email",
            return_value={"id": "msg_abc"},
        ) as send_mail,
    ):
        settings.resend_configured = True
        settings.admin_notification_email = "muhamadnas44@gmail.com"
        settings.auto_approve_email_set = set()
        res = client.post("/request-beta-access")

    assert res.status_code == 200
    body = res.json()
    assert body["success"] is True
    assert body["auto_approved"] is False
    assert body["message_id"] == "msg_abc"
    send_mail.assert_called_once()
    args, kwargs = send_mail.call_args
    assert args[0] == "muhamadnas44@gmail.com"
    assert args[1] == "New Beta Access Request: hr@acme.test"
    assert str(user_id) in args[2]
    assert kwargs.get("raise_on_error") is True


def test_request_beta_access_auto_approves(app, user_id):
    client = TestClient(app)
    corp_id = uuid4()
    with (
        patch("app.api.v1.beta_access.settings") as settings,
        patch(
            "app.api.v1.beta_access._auto_provision_hr_user",
            new_callable=AsyncMock,
            return_value=corp_id,
        ) as provision,
        patch("app.api.v1.beta_access.send_transactional_email") as send_mail,
    ):
        settings.auto_approve_email_set = {"hr@acme.test"}
        settings.resend_configured = False
        res = client.post("/request-beta-access")

    assert res.status_code == 200
    body = res.json()
    assert body["success"] is True
    assert body["auto_approved"] is True
    assert body["corporate_id"] == str(corp_id)
    provision.assert_awaited_once()
    send_mail.assert_not_called()


def test_request_beta_access_already_provisioned(user_id):
    application = FastAPI()
    application.include_router(router)

    async def _user():
        return SupabaseUserContext(
            user_id=user_id,
            email="hr@acme.test",
            corporate_id=uuid4(),
        )

    async def _db():
        yield MagicMock()

    application.dependency_overrides[get_current_supabase_user] = _user
    application.dependency_overrides[get_db] = _db
    client = TestClient(application)

    with patch("app.api.v1.beta_access.send_transactional_email") as send_mail:
        res = client.post("/request-beta-access")

    assert res.status_code == 200
    assert res.json()["already_provisioned"] is True
    send_mail.assert_not_called()


def test_request_beta_access_requires_resend(app):
    client = TestClient(app)
    with patch("app.api.v1.beta_access.settings") as settings:
        settings.resend_configured = False
        settings.auto_approve_email_set = set()
        res = client.post("/request-beta-access")
    assert res.status_code == 503


def test_request_beta_access_surfaces_resend_error(app):
    client = TestClient(app)
    with (
        patch("app.api.v1.beta_access.settings") as settings,
        patch(
            "app.api.v1.beta_access.send_transactional_email",
            side_effect=RuntimeError("Resend rejected the email: sandbox"),
        ),
    ):
        settings.resend_configured = True
        settings.admin_notification_email = "muhamadnas44@gmail.com"
        settings.auto_approve_email_set = set()
        res = client.post("/request-beta-access")
    assert res.status_code == 500
    assert "Resend rejected" in res.json()["detail"]


def test_auto_approve_emails_parsed_from_csv():
    from app.config import Settings

    cfg = Settings(AUTO_APPROVE_EMAILS="Dev@Example.com, qa@example.com")
    assert cfg.AUTO_APPROVE_EMAILS == ["dev@example.com", "qa@example.com"]
    assert "dev@example.com" in cfg.auto_approve_email_set
