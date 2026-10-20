import logging
from unittest.mock import MagicMock

import pytest

from app.services.email import (
    _source_address,
    clean_recipient_email,
    render_candidate_invite_html,
    render_candidate_nudge_html,
    render_hr_completion_html,
    render_package_share_html,
    render_universal_otp_html,
    resolve_frontend_origin,
    send_admin_otp_email,
    send_candidate_otp_email,
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


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("  pat@example.com  ", "pat@example.com"),
        ("Pat Lee <pat@example.com>", "pat@example.com"),
        ('"Pat Lee" <pat@example.com>;', "pat@example.com"),
        ("<pat@example.com>", "pat@example.com"),
        ("not-an-email", ""),
        (None, ""),
    ],
)
def test_clean_recipient_email(raw, expected):
    assert clean_recipient_email(raw) == expected


def test_source_address_falls_back_to_mindq_sender():
    assert _source_address(None) == "MindQ <noreply@mindqtalent.com>"
    assert _source_address("") == "MindQ <noreply@mindqtalent.com>"
    assert _source_address("MindQ <noreply@mindqtalent.com>") == (
        "MindQ <noreply@mindqtalent.com>"
    )


def test_send_transactional_email_sanitizes_recipient_and_sender(monkeypatch):
    monkeypatch.setattr("app.services.email.settings.EMAIL_FROM", "")
    monkeypatch.setattr("app.services.email.settings.AWS_REGION", "us-east-1")
    monkeypatch.setattr("app.services.email.settings.AWS_ACCESS_KEY_ID", "AKIATEST")
    monkeypatch.setattr("app.services.email.settings.AWS_SECRET_ACCESS_KEY", "secret")

    fake_client = MagicMock()
    fake_client.send_email.return_value = {"MessageId": "msg_clean"}
    monkeypatch.setattr("app.services.email._ses_client", lambda: fake_client)

    result = send_transactional_email(
        "  Pat Lee <pat@example.com> ",
        "Hello",
        "<p>Hi</p>",
    )

    assert result == {"id": "msg_clean", "MessageId": "msg_clean"}
    call_kwargs = fake_client.send_email.call_args.kwargs
    assert call_kwargs["Destination"]["ToAddresses"] == ["pat@example.com"]
    assert call_kwargs["Source"] == "MindQ <noreply@mindqtalent.com>"


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
async def test_email_service_senders_sanitize_recipients(monkeypatch):
    captured = {}

    async def fake_send(to_email, subject, html_content, raise_on_error=False):
        captured["to"] = to_email
        return {"id": "msg_clean"}

    monkeypatch.setattr(
        "app.services.email_service.send_transactional_email_async", fake_send
    )

    assert await EmailService.send_candidate_invite_email(
        email=" Pat Lee <pat@example.com> ",
        name="Pat",
        access_code="AP-TEST-1",
        package_title="Backend Pack",
    )
    assert captured["to"] == "pat@example.com"

    assert await EmailService.send_nudge_email(
        email=" Jane <jane@example.com>; ",
        name="Jane",
        access_code="AP-TEST-1",
        package_title="Backend Pack",
    )
    assert captured["to"] == "jane@example.com"

    assert await EmailService.send_hr_completion_email(
        hr_email=" HR <hr@example.com> ",
        hr_name="Harriet",
        candidate_name="Pat",
        package_title="Backend Pack",
        candidate_email="pat@example.com",
    )
    assert captured["to"] == "hr@example.com"


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
async def test_candidate_invite_logs_dispatch_even_when_ses_fails(monkeypatch, caplog):
    async def fake_send(to_email, subject, html_content, raise_on_error=False):
        return None

    monkeypatch.setattr(
        "app.services.email_service.send_transactional_email_async",
        fake_send,
    )
    with caplog.at_level(logging.INFO, logger="app.email_service"):
        ok = await EmailService.send_candidate_invite_email(
            email="Pat <pat@example.com>",
            name="Pat",
            access_code="AP-TEST-9",
            package_title="Backend Pack",
            origin="https://qa.app.mindqtalent.com",
        )

    assert ok is False
    logged = "\n".join(record.getMessage() for record in caplog.records)
    assert "[INVITE DISPATCHED] Candidate=pat@example.com" in logged
    assert "Code=AP-TEST-9" in logged
    assert "Link=https://qa.app.mindqtalent.com/assessment?code=AP-TEST-9" in logged
    assert "[INVITE FAILED]" in logged


DARK_MARKERS = ("#0B0F17", "#111827", "ASSESS PULSE", "#6B4CE8")


def _all_templates() -> dict[str, str]:
    return {
        "invite": render_candidate_invite_html(
            candidate_name="Pat",
            package_title="Backend Pack",
            access_code="HM-1",
            corporate_name="Acme",
            origin="https://qa.example.test",
        ),
        "nudge": render_candidate_nudge_html(
            candidate_name="Pat",
            package_title="Backend Pack",
            access_code="HM-1",
            origin="https://qa.example.test",
        ),
        "hr_completion": render_hr_completion_html(
            hr_name="Acme",
            candidate_name="Pat Lee",
            package_title="Backend Pack",
            candidate_email="pat@example.com",
        ),
        "package_share": render_package_share_html(
            corporate_name="Acme",
            package_title="Backend Pack",
            access_code="HM-1",
            origin="https://qa.example.test",
        ),
        "admin_otp": render_universal_otp_html("Admin Portal", "123456"),
        "candidate_otp": render_universal_otp_html("Candidate Portal", "654321"),
    }


def test_all_email_templates_use_the_light_theme():
    for name, html_content in _all_templates().items():
        assert "#FFFFFF" in html_content, name
        assert "#F9FAFB" in html_content, name
        assert "/branding/logo-light.png" in html_content, name
        assert 'alt="MindQ"' in html_content, name
        for marker in DARK_MARKERS:
            assert marker not in html_content, (name, marker)


def test_template_buttons_use_corporate_blue():
    templates = _all_templates()
    assert "#0078D4" in templates["invite"]
    assert "#0078D4" in templates["package_share"]


def test_universal_otp_is_prominent_escaped_and_time_boxed():
    html_content = render_universal_otp_html("Candidate Portal", "482916")
    assert "Candidate Portal" in html_content
    assert "482916" in html_content
    assert (
        "To access the <strong style=\"color:#1F2937;\">Candidate Portal</strong>, "
        "please use the verification code below. "
        "The code will expire in 5 minutes." in html_content
    )
    assert "font-size:36px" in html_content
    assert "letter-spacing:8px" in html_content
    assert "ui-monospace" in html_content
    assert "mailto:support@mindqtalent.com" in html_content
    assert "support@mindqtalent.com" in html_content

    malicious = render_universal_otp_html("<script>alert(1)</script>", "<b>1</b>")
    assert "<script>" not in malicious
    assert "&lt;script&gt;" in malicious
    assert "<b>1</b>" not in malicious


@pytest.mark.asyncio
async def test_candidate_otp_sender_uses_universal_template(monkeypatch):
    captured = {}

    async def fake_send(to_email, subject, html_content, raise_on_error=False):
        captured.update(to=to_email, subject=subject, html=html_content)
        return {"id": "msg_otp"}

    monkeypatch.setattr("app.services.email.send_transactional_email_async", fake_send)
    await send_candidate_otp_email("ada@example.com", "482916")
    assert captured["to"] == "ada@example.com"
    assert captured["subject"] == "Your MindQ Candidate Verification Code"
    assert "Candidate Portal" in captured["html"]
    assert "482916" in captured["html"]


@pytest.mark.asyncio
async def test_candidate_otp_falls_back_to_log_in_qa(monkeypatch, caplog):
    monkeypatch.setattr("app.services.email.settings.ENVIRONMENT", "qa")
    monkeypatch.setattr("app.services.email.settings.DEBUG", True)

    async def _rejected(*_args, **_kwargs):
        raise RuntimeError("SES rejected the email: MessageRejected: not verified")

    monkeypatch.setattr("app.services.email.send_transactional_email_async", _rejected)

    with caplog.at_level(logging.WARNING, logger="app.email"):
        result = await send_candidate_otp_email("ada@example.com", "482916")

    assert result is None
    logged = "\n".join(record.getMessage() for record in caplog.records)
    assert "QA/STAGING OTP FALLBACK" in logged
    assert "482916" in logged
    assert "Candidate Portal" in logged


@pytest.mark.asyncio
async def test_candidate_otp_raises_in_production(monkeypatch):
    monkeypatch.setattr("app.services.email.settings.ENVIRONMENT", "production")
    monkeypatch.setattr("app.services.email.settings.DEBUG", False)

    async def _rejected(*_args, **_kwargs):
        raise RuntimeError("SES rejected the email: MessageRejected: not verified")

    monkeypatch.setattr("app.services.email.send_transactional_email_async", _rejected)

    with pytest.raises(RuntimeError, match="MessageRejected"):
        await send_candidate_otp_email("ada@example.com", "482916")


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
