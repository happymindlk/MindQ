import logging
import sys
from types import ModuleType, SimpleNamespace
from unittest.mock import MagicMock

import pytest

from app.services.email import send_transactional_email
from app.services.email_service import EmailService


@pytest.mark.asyncio
async def test_nudge_without_resend_returns_false(monkeypatch, caplog):
    monkeypatch.setattr("app.services.email.settings.RESEND_API_KEY", None)

    with caplog.at_level(logging.WARNING, logger="app.email"):
        ok = await EmailService.send_nudge_email(
            email="jane@example.com",
            name="Jane",
            access_code="HM-ABCDEF-1",
            package_title="Engineering Aptitude",
        )

    assert ok is False
    logged = "\n".join(r.getMessage() for r in caplog.records)
    assert "Resend not configured" in logged
    assert "jane@example.com" in logged


def test_send_transactional_email_success(monkeypatch):
    monkeypatch.setattr("app.services.email.settings.RESEND_API_KEY", "re_test")
    monkeypatch.setattr(
        "app.services.email.settings.EMAIL_FROM",
        "Assess Pulse <onboarding@resend.dev>",
    )

    fake_resend = ModuleType("resend")
    fake_resend.Emails = SimpleNamespace(send=MagicMock(return_value={"id": "msg_123"}))
    monkeypatch.setitem(sys.modules, "resend", fake_resend)

    result = send_transactional_email(
        "jane@example.com",
        "Hello",
        "<p>Hi</p>",
    )
    assert result == {"id": "msg_123"}
    fake_resend.Emails.send.assert_called_once()
    call_payload = fake_resend.Emails.send.call_args[0][0]
    assert call_payload["to"] == ["jane@example.com"]
    assert call_payload["from"] == "Assess Pulse <onboarding@resend.dev>"


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
    )
    assert ok is True
    assert "Backend Pack" in captured["subject"]
    assert "Acme Corp" in captured["subject"]
    assert "AP-TEST-1" in captured["html"]
    assert "Acme Corp" in captured["html"]
    assert "Guidelines" in captured["html"]
    assert "Start assessment" in captured["html"]
    assert "/assessment?code=AP-TEST-1" in captured["html"]


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
