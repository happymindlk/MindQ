"""Transactional email via AWS SES.

Provides a sync, BackgroundTasks-safe sender plus HTML templates for candidate
invite and HR completion notifications. Never raises to callers — failures are
logged and return None — unless ``raise_on_error`` is True.
"""
from __future__ import annotations

import functools
import html
import logging
import re
from email.utils import parseaddr
from typing import Any
from urllib.parse import quote, urlparse

from starlette.concurrency import run_in_threadpool
from starlette.requests import Request

from app.config import settings

logger = logging.getLogger("app.email")

PRODUCTION_FRONTEND_URL = "https://mindq.pages.dev"
DEFAULT_EMAIL_FROM = "MindQ <noreply@mindqtalent.com>"
_LOCALHOST_HOSTS = frozenset({"localhost", "127.0.0.1", "0.0.0.0", "::1"})
_FROM_ANGLE = re.compile(r"<\s*([^>\s]+)\s*>")
_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")


def clean_recipient_email(value: object) -> str:
    """Extract a bare recipient address safe for SES ``ToAddresses``.

    Strips display names, angle brackets, surrounding quotes, and trailing
    whitespace/punctuation, e.g. ``"Pat <pat@example.com> "`` becomes
    ``pat@example.com``.

    Args:
        value: Raw recipient value in any shape.

    Returns:
        The bare email address, or ``""`` when none can be extracted.
    """
    if value is None:
        return ""
    raw = str(value).strip()
    if not raw:
        return ""
    _, parsed = parseaddr(raw)
    candidate = (parsed or raw).strip().strip("<>").strip().strip("\"'").rstrip(";,")
    match = _EMAIL_RE.search(candidate) or _EMAIL_RE.search(raw)
    if match:
        return match.group(0).rstrip(";,.")
    return candidate if "@" in candidate else ""


def _is_localhost_origin(origin: str) -> bool:
    """Return True when ``origin`` points at a loopback host."""
    parsed = urlparse(origin)
    host = (parsed.hostname or "").lower()
    return host in _LOCALHOST_HOSTS


def resolve_frontend_origin(request: Request | None = None) -> str:
    """Public React app origin (no trailing slash).

    Priority: ``settings.FRONTEND_URL`` → request ``Origin`` / ``Referer`` →
    production Pages URL. Localhost settings are honoured when explicitly set
    so local email previews still work; blank settings fall through.

    Args:
        request: Optional incoming request used for Origin / Referer fallback.

    Returns:
        Absolute origin such as ``https://mindq.pages.dev``.
    """
    explicit = (settings.FRONTEND_URL or "").rstrip("/")
    if explicit:
        return explicit

    portal = (settings.PORTAL_URL or "").rstrip("/")
    if portal:
        if portal.endswith("/portal"):
            return portal[: -len("/portal")]
        parsed_portal = urlparse(portal)
        if parsed_portal.scheme and parsed_portal.netloc:
            return f"{parsed_portal.scheme}://{parsed_portal.netloc}"

    if request is not None:
        origin = (request.headers.get("origin") or "").rstrip("/")
        if origin and not _is_localhost_origin(origin):
            return origin
        referer = (request.headers.get("referer") or "").strip()
        if referer:
            parsed = urlparse(referer)
            if parsed.scheme and parsed.netloc and not _is_localhost_origin(
                f"{parsed.scheme}://{parsed.netloc}"
            ):
                return f"{parsed.scheme}://{parsed.netloc}"

    return PRODUCTION_FRONTEND_URL


def frontend_origin(request: Request | None = None) -> str:
    """Public origin of the React app, without a trailing slash."""
    return resolve_frontend_origin(request)


def _assessment_invite_link(access_code: str, *, origin: str | None = None) -> str:
    """Candidate CTA: ``{origin}/assessment?code={access_code}``."""
    base = (origin or frontend_origin()).rstrip("/")
    return f"{base}/assessment?code={quote(str(access_code))}"


def _portal_link(access_code: str, *, origin: str | None = None) -> str:
    return candidate_portal_link(access_code, origin=origin)


def candidate_portal_link(access_code: str, *, origin: str | None = None) -> str:
    """Universal candidate link that pre-fills the access code on the portal login.

    Args:
        access_code: Package access code (doubles as the candidate PIN).
        origin: Optional absolute frontend origin; defaults to ``frontend_origin()``.

    Returns:
        Absolute URL ``{FRONTEND}/portal?code={access_code}``.
    """
    base = (origin or frontend_origin()).rstrip("/")
    return f"{base}/portal?code={quote(str(access_code))}"


def hr_portal_login_link(*, origin: str | None = None) -> str:
    """Absolute URL of the HR client portal login.

    Args:
        origin: Optional absolute frontend origin; defaults to ``frontend_origin()``.

    Returns:
        ``{FRONTEND}/client/login``.
    """
    base = (origin or frontend_origin()).rstrip("/")
    return f"{base}/client/login"


# ---------------------------------------------------------------------------
# Light-theme email shell (white card on a light-gray wrapper, MindQ logo)
# ---------------------------------------------------------------------------

_HEADING_STYLE = "font-size:22px;margin:0 0 12px;color:#1F2937;"
_BODY_STYLE = "font-size:14px;line-height:1.55;color:#4B5563;"
_MUTED_STYLE = "font-size:12px;color:#6B7280;"
_BUTTON_STYLE = (
    "display:inline-block;padding:12px 20px;background:#0078D4;color:#FFFFFF;"
    "text-decoration:none;border-radius:8px;font-weight:700;font-size:14px;"
)
_CODE_BOX_STYLE = (
    "margin:0 0 24px;padding:14px 16px;background:#F3F4F6;"
    "border:1px solid #E5E7EB;border-radius:8px;"
    "font-family:ui-monospace,Consolas,monospace;font-size:18px;"
    "color:#1F2937;letter-spacing:0.06em;"
)


def _light_email_shell(body_html: str, *, origin: str | None = None) -> str:
    """Wrap ``body_html`` in the shared light-theme MindQ email shell.

    Args:
        body_html: Inner card content (already escaped by the caller).
        origin: Optional frontend origin for the logo URL; defaults to
            ``frontend_origin()``.

    Returns:
        Full HTML document with a light-gray wrapper, white card, and logo.
    """
    base = (origin or frontend_origin()).rstrip("/")
    logo_url = html.escape(f"{base}/branding/logo-light.png")
    return f"""<!DOCTYPE html>
<html><body style="margin:0;padding:0;background:#F9FAFB;color:#1F2937;font-family:Segoe UI,Helvetica,Arial,sans-serif;">
  <div style="max-width:560px;margin:0 auto;padding:32px 20px;">
    <div style="background:#FFFFFF;border:1px solid #E5E7EB;border-radius:12px;padding:32px 28px;">
      <img src="{logo_url}" alt="MindQ" style="height:32px;margin-bottom:24px;" />
      {body_html}
    </div>
  </div>
</body></html>"""


def _ses_client():
    """Build a boto3 SES client from settings / the default credential chain."""
    import boto3

    kwargs: dict[str, Any] = {"region_name": (settings.AWS_REGION or "us-east-1").strip()}
    key = (settings.AWS_ACCESS_KEY_ID or "").strip()
    secret = (settings.AWS_SECRET_ACCESS_KEY or "").strip()
    if key and secret:
        kwargs["aws_access_key_id"] = key
        kwargs["aws_secret_access_key"] = secret
    return boto3.client("ses", **kwargs)


def _source_address(from_addr: str | None) -> str:
    """Normalize ``Name <email>`` or bare email for SES ``Source``.

    Falls back to ``MindQ <noreply@mindqtalent.com>`` when unset or unusable.
    """
    raw = (from_addr or "").strip()
    if not raw:
        return DEFAULT_EMAIL_FROM
    if not clean_recipient_email(raw):
        return DEFAULT_EMAIL_FROM
    if _FROM_ANGLE.search(raw):
        return raw
    return clean_recipient_email(raw)


def _ses_error_hint(exc: BaseException) -> str:
    """Human-readable hint for common SES sandbox / identity failures."""
    text = str(exc).lower()
    if "not verified" in text or "messagerejected" in text or "email address is not verified" in text:
        return (
            "SES sandbox/identity: verify the From address AND every recipient "
            "(or request production access) in AWS SES → Configuration → Identities."
        )
    if "accessdenied" in text or "not authorized" in text:
        return "IAM: ensure the AWS key can call ses:SendEmail in this region."
    if "invalidclienttokenid" in text or "signature" in text:
        return "Credentials: AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY look invalid."
    return ""


def send_transactional_email(
    to_email: str,
    subject: str,
    html_content: str,
    *,
    raise_on_error: bool = False,
) -> dict | None:
    """Send one HTML email through AWS SES.

    Safe for FastAPI ``BackgroundTasks``: all failures are caught and logged with
    a full stack trace (``logger.exception``) unless ``raise_on_error`` is True.

    Args:
        to_email: Recipient address.
        subject: Message subject line.
        html_content: Full HTML body.
        raise_on_error: When True, propagate SES failures as RuntimeError
            instead of returning None (used by beta-access where the UI must
            reflect delivery errors).

    Returns:
        Dict with ``id`` (SES MessageId) on success, otherwise None when
        ``raise_on_error`` is False.
    """
    clean_email = clean_recipient_email(to_email)
    if not clean_email:
        logger.error(
            "SES send aborted: no valid recipient extracted from %r subject=%r",
            to_email,
            subject,
        )
        if raise_on_error:
            raise RuntimeError(f"Invalid recipient email: {to_email!r}")
        return None

    from_addr = _source_address(getattr(settings, "EMAIL_FROM", None))

    # EMAIL_FROM falls back to DEFAULT_EMAIL_FROM, so configuration hinges on
    # region + credentials rather than a (possibly blank) sender override.
    ses_ready = bool(
        (getattr(settings, "AWS_REGION", "") or "").strip()
        and (getattr(settings, "AWS_ACCESS_KEY_ID", "") or "").strip()
        and (getattr(settings, "AWS_SECRET_ACCESS_KEY", "") or "").strip()
    )
    if not ses_ready:
        msg = (
            f"SES not configured; skipping email to {clean_email} subject={subject!r}. "
            "Set AWS_REGION, AWS_ACCESS_KEY_ID, and AWS_SECRET_ACCESS_KEY."
        )
        logger.warning(msg)
        if raise_on_error:
            raise RuntimeError(
                "SES is not configured (AWS_REGION / AWS credentials missing)"
            )
        return None

    logger.info(
        "SES send starting to=%s from=%s subject=%r region=%s",
        clean_email,
        from_addr,
        subject,
        settings.AWS_REGION,
    )

    try:
        response = _ses_client().send_email(
            Source=from_addr,
            Destination={"ToAddresses": [clean_email]},
            Message={
                "Subject": {"Data": subject, "Charset": "UTF-8"},
                "Body": {"Html": {"Data": html_content, "Charset": "UTF-8"}},
            },
        )
        message_id = response.get("MessageId")
        payload: dict[str, Any] = {"id": message_id, "MessageId": message_id}
        logger.info(
            "SES email sent successfully to=%s MessageId=%s subject=%r",
            clean_email,
            message_id,
            subject,
        )
        return payload
    except Exception as exc:  # noqa: BLE001 — BackgroundTasks must never raise silently
        hint = _ses_error_hint(exc)
        # logger.exception always includes a full traceback for journalctl / CloudWatch.
        logger.exception(
            "SES send FAILED to=%s from=%s subject=%r error=%s%s",
            clean_email,
            from_addr,
            subject,
            exc,
            f" | hint={hint}" if hint else "",
        )
        try:
            from botocore.exceptions import ClientError

            if isinstance(exc, ClientError):
                err = (exc.response or {}).get("Error") or {}
                logger.error(
                    "AWS SES ClientError code=%s message=%s to=%s",
                    err.get("Code"),
                    err.get("Message"),
                    clean_email,
                )
        except ImportError:
            pass
        if raise_on_error:
            detail = f"SES rejected the email: {exc}"
            if hint:
                detail = f"{detail} ({hint})"
            raise RuntimeError(detail) from exc
        return None


async def send_transactional_email_async(
    to_email: str,
    subject: str,
    html_content: str,
    *,
    raise_on_error: bool = False,
) -> dict | None:
    """Async wrapper around the sync SES call (threadpool)."""
    send = functools.partial(
        send_transactional_email,
        to_email,
        subject,
        html_content,
        raise_on_error=raise_on_error,
    )
    return await run_in_threadpool(send)


def render_candidate_invite_html(
    *,
    candidate_name: str,
    package_title: str,
    access_code: str,
    corporate_name: str | None = None,
    origin: str | None = None,
) -> str:
    """HTML for the candidate assessment invite / magic-link email."""
    name = html.escape(candidate_name or "there")
    title = html.escape(package_title or "your assessment")
    company = html.escape((corporate_name or "").strip() or "Your hiring team")
    code = html.escape(access_code)
    link = html.escape(_assessment_invite_link(access_code, origin=origin))
    body = f"""
      <h1 style="{_HEADING_STYLE}">You're invited to complete an assessment</h1>
      <p style="{_BODY_STYLE}margin:0 0 20px;">
        <strong style="color:#1F2937;">{company}</strong> has invited
        <strong style="color:#1F2937;">{name}</strong> to complete
        <strong style="color:#1F2937;">{title}</strong>.
      </p>
      <p style="{_BODY_STYLE}margin:0 0 8px;">Your access code:</p>
      <div style="{_CODE_BOX_STYLE}">
        {code}
      </div>
      <a href="{link}" style="{_BUTTON_STYLE}">
        Start assessment
      </a>
      <div style="margin-top:28px;padding-top:16px;border-top:1px solid #E5E7EB;">
        <p style="font-size:13px;line-height:1.5;color:#4B5563;margin:0 0 8px;"><strong style="color:#1F2937;">Guidelines</strong></p>
        <ul style="margin:0;padding-left:18px;color:#4B5563;font-size:13px;line-height:1.55;">
          <li>Find a quiet place with a stable internet connection.</li>
          <li>Your answers autosave — you can leave and return with the same code.</li>
          <li>Complete each section in one sitting when possible.</li>
        </ul>
      </div>
      <p style="{_MUTED_STYLE}margin-top:28px;">If the button doesn't work, paste this link into your browser:<br>{link}</p>"""
    return _light_email_shell(body, origin=origin)


def render_hr_completion_html(
    *,
    hr_name: str | None,
    candidate_name: str,
    package_title: str,
    candidate_email: str,
) -> str:
    """HTML alerting HR that a candidate finished and the report is ready."""
    greeting = html.escape((hr_name or "there").strip() or "there")
    cand = html.escape(candidate_name)
    title = html.escape(package_title or "assessment package")
    email = html.escape(candidate_email)
    body = f"""
      <h1 style="{_HEADING_STYLE}">Candidate completed assessment</h1>
      <p style="{_BODY_STYLE}margin:0 0 16px;">
        Hello <strong style="color:#1F2937;">{greeting}</strong>,
        <strong style="color:#1F2937;">{cand}</strong> ({email}) has finished
        <strong style="color:#1F2937;">{title}</strong>.
      </p>
      <p style="{_BODY_STYLE}margin:0 0 20px;">
        Their report is ready to download from the HR Tracker. JD fit scoring may still be finishing in the background.
      </p>
      <div style="margin:0 0 8px;padding:14px 16px;background:#F3F4F6;border:1px solid #E5E7EB;border-radius:8px;font-size:13px;color:#4B5563;">
        Open <strong style="color:#1F2937;">MindQ → HR Tracker</strong> and download the report for this candidate.
      </div>
      <p style="{_MUTED_STYLE}margin-top:28px;">This is an automated notification from MindQ.</p>"""
    return _light_email_shell(body)


def render_candidate_nudge_html(
    *,
    candidate_name: str,
    package_title: str,
    access_code: str,
    origin: str | None = None,
) -> str:
    """HTML reminder for an incomplete candidate."""
    name = html.escape(candidate_name or "there")
    title = html.escape(package_title or "your assessment")
    code = html.escape(access_code)
    link = html.escape(_portal_link(access_code, origin=origin))
    body = f"""
      <h1 style="{_HEADING_STYLE}">Friendly reminder</h1>
      <p style="{_BODY_STYLE}margin:0 0 16px;">
        Hello <strong style="color:#1F2937;">{name}</strong>, please finish your
        <strong style="color:#1F2937;">{title}</strong> assessment when you can.
      </p>
      <div style="{_CODE_BOX_STYLE}">
        {code}
      </div>
      <a href="{link}" style="{_BUTTON_STYLE}">
        Continue assessment
      </a>"""
    return _light_email_shell(body, origin=origin)


def render_package_share_html(
    *,
    corporate_name: str | None,
    package_title: str,
    access_code: str,
    origin: str | None = None,
) -> str:
    """HTML handing a client both candidate access and HR portal access for a package.

    Args:
        corporate_name: Client company display name.
        package_title: Published package title.
        access_code: Package access code, shown to candidates as the PIN.
        origin: Optional absolute frontend origin for links.

    Returns:
        Full HTML document for SES.
    """
    company = html.escape((corporate_name or "").strip() or "your team")
    title = html.escape(package_title or "your assessment")
    code = html.escape(access_code)
    candidate_link = html.escape(candidate_portal_link(access_code, origin=origin))
    hr_link = html.escape(hr_portal_login_link(origin=origin))
    section = "margin:0 0 20px;padding:16px;background:#F9FAFB;border:1px solid #E5E7EB;border-radius:8px;"
    label = "font-size:11px;font-weight:700;letter-spacing:0.08em;color:#0078D4;margin:0 0 10px;"
    section_body = "font-size:13px;line-height:1.55;color:#4B5563;margin:0 0 12px;"
    mono = "font-family:ui-monospace,Consolas,monospace;"
    button = (
        "display:inline-block;padding:10px 16px;background:#0078D4;color:#FFFFFF;"
        "text-decoration:none;border-radius:8px;font-weight:700;font-size:13px;"
    )
    body_html = f"""
      <h1 style="{_HEADING_STYLE}">{title} is ready to share</h1>
      <p style="{_BODY_STYLE}margin:0 0 24px;">
        Hello <strong style="color:#1F2937;">{company}</strong>, your assessment is live.
        Forward the candidate details below to applicants, and use the HR portal to track results.
      </p>

      <div style="{section}">
        <p style="{label}">CANDIDATE ACCESS</p>
        <p style="{section_body}">Candidates open this link and enter the PIN with their name and email.</p>
        <p style="font-size:12px;color:#4B5563;margin:0 0 4px;">Test link</p>
        <p style="{mono}font-size:13px;color:#1F2937;margin:0 0 12px;word-break:break-all;">
          <a href="{candidate_link}" style="color:#0078D4;">{candidate_link}</a>
        </p>
        <p style="font-size:12px;color:#4B5563;margin:0 0 4px;">PIN</p>
        <p style="{mono}font-size:18px;color:#1F2937;letter-spacing:0.06em;margin:0;">{code}</p>
      </div>

      <div style="{section}">
        <p style="{label}">HR PORTAL ACCESS</p>
        <p style="{section_body}">Sign in to follow candidate progress and download reports.</p>
        <a href="{hr_link}" style="{button}">Open HR portal</a>
        <p style="{mono}font-size:12px;color:#6B7280;margin:12px 0 0;word-break:break-all;">{hr_link}</p>
      </div>

      <p style="{_MUTED_STYLE}margin-top:28px;">This message was sent by MindQ on behalf of your account team.</p>"""
    return _light_email_shell(body_html, origin=origin)


def admin_otp_message(otp: str) -> str:
    """Plain-text body of the admin sign-in code email.

    Args:
        otp: Six-digit verification code.

    Returns:
        The sentence delivered to the admin inbox.
    """
    return f"Your MindQ Admin Verification Code is: {otp}. Valid for 5 minutes."


def render_universal_otp_html(portal_name: str, otp: str) -> str:
    """Microsoft-style verification-code email shared by every portal.

    Args:
        portal_name: Display name of the portal the code unlocks
            (e.g. ``"Admin Portal"``, ``"Candidate Portal"``).
        otp: Six-digit verification code.

    Returns:
        Light-theme HTML document with the code prominent in a gray box.
    """
    portal = html.escape(portal_name)
    code = html.escape(otp)
    body = f"""
      <p style="{_BODY_STYLE}margin:0 0 20px;">
        To access the <strong style="color:#1F2937;">{portal}</strong>, please use the verification code below. The code will expire in 5 minutes.
      </p>
      <div style="margin:0 0 24px;padding:20px 16px;background:#F3F4F6;border:1px solid #E5E7EB;border-radius:8px;text-align:center;">
        <span style="font-family:ui-monospace,'Cascadia Mono',Consolas,monospace;font-size:36px;font-weight:700;letter-spacing:8px;color:#1F2937;">{code}</span>
      </div>
      <p style="font-size:13px;line-height:1.5;color:#4B5563;margin:0 0 24px;">If you did not request this code, you can ignore this email.</p>
      <p style="{_MUTED_STYLE}margin:0;padding-top:16px;border-top:1px solid #E5E7EB;">
        Need help? Contact us at <a href="mailto:support@mindqtalent.com" style="color:#0078D4;">support@mindqtalent.com</a>
      </p>"""
    return _light_email_shell(body)


def render_admin_otp_html(otp: str) -> str:
    """HTML wrapper for the admin sign-in code (universal OTP template).

    Args:
        otp: Six-digit verification code.

    Returns:
        HTML document from ``render_universal_otp_html`` for the Admin Portal.
    """
    return render_universal_otp_html("Admin Portal", otp)


def _otp_log_fallback_enabled() -> bool:
    """True when a failed SES OTP may be logged for QA/staging testing.

    Non-production means ``ENVIRONMENT != 'production'`` or ``DEBUG`` is on.
    In production (``ENVIRONMENT=production`` and ``DEBUG=false``) the code
    is never written to logs and delivery failures keep raising.
    """
    environment = (getattr(settings, "ENVIRONMENT", "") or "").strip().lower()
    return environment != "production" or bool(getattr(settings, "DEBUG", False))


def _log_otp_fallback(
    to_email: str, otp: str, exc: BaseException, *, portal_name: str
) -> None:
    """Log a prominent banner carrying the OTP after an SES failure (QA only).

    Args:
        to_email: Inbox the code was meant for.
        otp: Six-digit verification code.
        exc: SES / mailer failure that triggered the fallback.
        portal_name: Portal the code unlocks (for the action line).
    """
    banner = "\n".join(
        [
            "",
            "=" * 70,
            "  !!!  SES DELIVERY FAILED - QA/STAGING OTP FALLBACK  !!!",
            "  (ENVIRONMENT != 'production' or DEBUG - never enable in prod)",
            "=" * 70,
            f"  Recipient : {to_email}",
            f"  Portal    : {portal_name}",
            f"  OTP CODE  : {otp}",
            f"  Error     : {type(exc).__name__}: {exc}",
            f"  Action    : enter the OTP code above on the {portal_name} login screen.",
            "=" * 70,
            "",
        ]
    )
    logger.warning(banner)


def _log_admin_otp_fallback(to_email: str, otp: str, exc: BaseException) -> None:
    """Log the QA fallback banner for an admin OTP (see ``_log_otp_fallback``)."""
    _log_otp_fallback(to_email, otp, exc, portal_name="Admin Portal")


async def _send_portal_otp_email(
    to_email: str, otp: str, *, portal_name: str, subject: str
) -> None:
    """Deliver a portal OTP through SES with the QA log fallback.

    Production: delivery failures raise so the caller can discard the
    challenge instead of issuing a temp token nobody can complete.

    QA/staging (non-production): SES failures (e.g. sandbox ``MessageRejected``
    for an unverified recipient) are caught, the code is logged in a prominent
    banner for testers, and the function returns successfully so the
    login-challenge transaction is committed, not rolled back.

    Args:
        to_email: Inbox that requested sign-in.
        otp: Six-digit verification code.
        portal_name: Portal display name used in the template and fallback.
        subject: Message subject line.

    Raises:
        RuntimeError: In production, when the mailer is not configured or
            rejected the message.
    """
    try:
        result = await send_transactional_email_async(
            to_email,
            subject,
            render_universal_otp_html(portal_name, otp),
            raise_on_error=True,
        )
        if not result:
            raise RuntimeError("Verification email was not sent")
    except Exception as exc:  # noqa: BLE001 - re-raised in production below
        if _otp_log_fallback_enabled():
            logger.exception(
                "%s OTP SES delivery failed; using QA log fallback to=%s",
                portal_name,
                to_email,
            )
            _log_otp_fallback(to_email, otp, exc, portal_name=portal_name)
            return
        if isinstance(exc, RuntimeError):
            raise
        raise RuntimeError(f"Verification email was not sent: {exc}") from exc


async def send_admin_otp_email(to_email: str, otp: str) -> None:
    """Deliver an admin sign-in code (see ``_send_portal_otp_email``).

    Args:
        to_email: Admin inbox that just passed the password check.
        otp: Six-digit verification code.

    Raises:
        RuntimeError: In production, when delivery fails.
    """
    await _send_portal_otp_email(
        to_email,
        otp,
        portal_name="Admin Portal",
        subject="Your MindQ Admin Verification Code",
    )


async def send_hr_otp_email(to_email: str, otp: str) -> None:
    """Deliver an HR/client sign-in code (see ``_send_portal_otp_email``).

    Args:
        to_email: HR inbox that requested sign-in. Cleaned again by
            ``send_transactional_email`` before SES dispatch.
        otp: Six-digit verification code.

    Raises:
        RuntimeError: In production, when delivery fails.
    """
    await _send_portal_otp_email(
        to_email,
        otp,
        portal_name="HR & Client Portal",
        subject="Your MindQ HR & Client Portal Verification Code",
    )


async def send_candidate_otp_email(to_email: str, otp: str) -> None:
    """Deliver a candidate sign-in code (see ``_send_portal_otp_email``).

    Args:
        to_email: Candidate inbox that requested a code.
        otp: Six-digit verification code.

    Raises:
        RuntimeError: In production, when delivery fails.
    """
    await _send_portal_otp_email(
        to_email,
        otp,
        portal_name="Candidate Portal",
        subject="Your MindQ Candidate Verification Code",
    )
