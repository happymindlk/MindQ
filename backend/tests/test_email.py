import logging
from unittest.mock import MagicMock

import pytest

from app.services.email import (
    resolve_frontend_origin,
    send_admin_otp_email,
    send_transactional_email,
)
from app.services.email_service import EmailService


@pytest.mark.asyncio
async def test_nudge_without_ses_returns_false(monkeypatch, caplog):
    monkeypatch.setattr("app.services.email.settings.EMAIL_FROM", "")
    monkeypatch.setattr("app.services.email.settings.AWS_REGION", "")

    with caplog.at_level(logging.WARNING, logger="app.email"):
        ok = await EmailService.send_nudge_email(
            email="jane@example.com",
            name="Jane",
            access_code="HM-ABCDEF-1",
            package_title="Engineering Aptitude",
        )

    assert ok is False
    logged = "\n".join(r.getMessage() for r in caplog.records)
    assert "SES not configured" in logged
    assert "jane@example.com" in logged


def test_send_transactional_email_success(monkeypatch):
    monkeypatch.setattr("app.services.email.settings.EMAIL_FROM", "Assess Pulse <noreply@example.com>")
    monkeypatch.setattr("app.services.email.settings.AWS_REGION", "us-east-1")
    monkeypatch.setattr("app.services.email.settings.AWS_ACCESS_KEY_ID", "AKIATEST")
    monkeypatch.setattr("app.services.email.settings.AWS_SECRET_ACCESS_KEY", "secret")

    fake_client = MagicMock()
    fake_client.send_email.return_value = {"MessageId": "msg_123"}
    monkeypatch.setattr("app.services.email._ses_client", lambda: fake_client)

    result = send_transactional_email(
        "jane@example.com",
        "Hello",
        "<p>Hi</p>",
    )
    assert result == {"id": "msg_123", "MessageId": "msg_123"}
    fake_client.send_email.assert_called_once()
    call_kwargs = fake_client.send_email.call_args.kwargs
    assert call_kwargs["Destination"]["ToAddresses"] == ["jane@example.com"]
    assert call_kwargs["Source"] == "Assess Pulse <noreply@example.com>"


def test_send_transactional_email_logs_client_error(monkeypatch, caplog):
    monkeypatch.setattr("app.services.email.settings.EMAIL_FROM", "Assess Pulse <noreply@example.com>")
    monkeypatch.setattr("app.services.email.settings.AWS_REGION", "us-east-1")
    monkeypatch.setattr("app.services.email.settings.AWS_ACCESS_KEY_ID", "AKIATEST")
    monkeypatch.setattr("app.services.email.settings.AWS_SECRET_ACCESS_KEY", "secret")

    from botocore.exceptions import ClientError

    err = ClientError(
        {
            "Error": {
                "Code": "MessageRejected",
                "Message": "Email address is not verified.",
            }
        },
        "SendEmail",
    )
    fake_client = MagicMock()
    fake_client.send_email.side_effect = err
    monkeypatch.setattr("app.services.email._ses_client", lambda: fake_client)

    with caplog.at_level(logging.ERROR, logger="app.email"):
        result = send_transactional_email("muhamadnas44@gmail.com", "Hello", "<p>Hi</p>")

    assert result is None
    logged = "\n".join(r.getMessage() for r in caplog.records)
    assert "SES send FAILED" in logged
    assert "not verified" in logged.lower() or "MessageRejected" in logged
    assert "sandbox" in logged.lower() or "Identities" in logged


def test_resolve_frontend_origin_prefers_settings(monkeypatch):
    monkeypatch.setattr(
        "app.services.email.settings.FRONTEND_URL", "https://app.example.test"
    )
    assert resolve_frontend_origin() == "https://app.example.test"


def test_resolve_frontend_origin_falls_back_to_production(monkeypatch):
    monkeypatch.setattr("app.services.email.settings.FRONTEND_URL", "")
    monkeypatch.setattr("app.services.email.settings.PORTAL_URL", "")
    assert resolve_frontend_origin() == "https://mindq.pages.dev"


@pytest.mark.asyncio
async def test_invite_email_includes_guidelines(monkeypatch):
    captured = {}

    async def fake_send(to_email, subject, html_content, raise_on_error=False):
        captured["to"] = to_email
        captured["subject"] = subject
        captured["html"] = html_content
        return {"id": "msg_invite"}

    monkeypatch.setattr(
        "app.services.email_service.send_transactional_email_async",
        fake_send,
    )
    ok = await EmailService.send_candidate_invite_email(
        email="pat@example.com",
        name="Pat",
        access_code="AP-TEST-1",
        package_title="Backend Pack",
        corporate_name="Acme Corp",
        origin="https://mindq.pages.dev",
    )
    assert ok is True
    assert "Backend Pack" in captured["subject"]
    assert "Acme Corp" in captured["subject"]
    assert "AP-TEST-1" in captured["html"]
    assert "Acme Corp" in captured["html"]
    assert "Guidelines" in captured["html"]
    assert "Start assessment" in captured["html"]
    assert "https://mindq.pages.dev/assessment?code=AP-TEST-1" in captured["html"]


@pytest.mark.asyncio
async def test_admin_otp_falls_back_to_log_in_qa(monkeypatch, caplog):
    """SES sandbox rejection must not raise (or roll back) outside production."""
    monkeypatch.setattr("app.services.email.settings.ENVIRONMENT", "qa")
    monkeypatch.setattr("app.services.email.settings.DEBUG", True)

    async def _rejected(*_args, **_kwargs):
        raise RuntimeError("SES rejected the email: MessageRejected: not verified")

    monkeypatch.setattr(
        "app.services.email.send_transactional_email_async", _rejected
    )

    with caplog.at_level(logging.WARNING, logger="app.email"):
        result = await send_admin_otp_email("ops@mindq.test", "482916")

    assert result is None
    logged = "\n".join(record.getMessage() for record in caplog.records)
    assert "QA/STAGING OTP FALLBACK" in logged
    assert "482916" in logged
    assert "ops@mindq.test" in logged


@pytest.mark.asyncio
async def test_admin_otp_raises_in_production(monkeypatch):
    monkeypatch.setattr("app.services.email.settings.ENVIRONMENT", "production")
    monkeypatch.setattr("app.services.email.settings.DEBUG", False)

    async def _rejected(*_args, **_kwargs):
        raise RuntimeError("SES rejected the email: MessageRejected: not verified")

    monkeypatch.setattr(
        "app.services.email.send_transactional_email_async", _rejected
    )

    with pytest.raises(RuntimeError, match="MessageRejected"):
        await send_admin_otp_email("ops@mindq.test", "482916")


@pytest.mark.asyncio
async def test_hr_completion_email(monkeypatch):
    captured = {}

    async def fake_send(to_email, subject, html_content, raise_on_error=False):
        captured["to"] = to_email
        captured["subject"] = subject
        captured["html"] = html_content
        return {"id": "msg_hr"}

    monkeypatch.setattr(
        "app.services.email_service.send_transactional_email_async",
        fake_send,
    )
    ok = await EmailService.send_hr_completion_email(
        "hr@acme.com",
        candidate_name="Pat Lee",
        candidate_email="pat@example.com",
        package_title="Backend Pack",
        hr_name="Acme Corp",
    )
    assert ok is True
    assert captured["to"] == "hr@acme.com"
    assert "Pat Lee" in captured["subject"]
    assert "finished" in captured["html"].lower() or "completed" in captured["html"].lower()
