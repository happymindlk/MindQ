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
from typing import Any
from urllib.parse import quote, urlparse

from starlette.concurrency import run_in_threadpool
from starlette.requests import Request

from app.config import settings

logger = logging.getLogger("app.email")

PRODUCTION_FRONTEND_URL = "https://mindq.pages.dev"
_LOCALHOST_HOSTS = frozenset({"localhost", "127.0.0.1", "0.0.0.0", "::1"})
_FROM_ANGLE = re.compile(r"<\s*([^>\s]+)\s*>")


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


def _source_address(from_addr: str) -> str:
    """Normalize ``Name <email>`` or bare email for SES ``Source``."""
    match = _FROM_ANGLE.search(from_addr or "")
    if match:
        return from_addr.strip()
    return (from_addr or "").strip()


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
    if not settings.email_configured:
        msg = (
            f"SES not configured; skipping email to {to_email} subject={subject!r}. "
            "Set AWS_REGION, AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY, and EMAIL_FROM."
        )
        logger.warning(msg)
        if raise_on_error:
            raise RuntimeError(
                "SES is not configured (AWS_REGION / EMAIL_FROM / AWS credentials missing)"
            )
        return None

    from_addr = _source_address(settings.EMAIL_FROM)
    logger.info(
        "SES send starting to=%s from=%s subject=%r region=%s",
        to_email,
        from_addr,
        subject,
        settings.AWS_REGION,
    )

    try:
        response = _ses_client().send_email(
            Source=from_addr,
            Destination={"ToAddresses": [to_email]},
            Message={
                "Subject": {"Data": subject, "Charset": "UTF-8"},
                "Body": {"Html": {"Data": html_content, "Charset": "UTF-8"}},
            },
        )
        message_id = response.get("MessageId")
        payload: dict[str, Any] = {"id": message_id, "MessageId": message_id}
        logger.info(
            "SES email sent successfully to=%s MessageId=%s subject=%r",
            to_email,
            message_id,
            subject,
        )
        return payload
    except Exception as exc:  # noqa: BLE001 — BackgroundTasks must never raise silently
        hint = _ses_error_hint(exc)
        # logger.exception always includes a full traceback for journalctl / CloudWatch.
        logger.exception(
            "SES send FAILED to=%s from=%s subject=%r error=%s%s",
            to_email,
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
                    to_email,
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
    return f"""<!DOCTYPE html>
<html><body style="margin:0;padding:0;background:#0B0F17;color:#E8EDF5;font-family:Segoe UI,Helvetica,Arial,sans-serif;">
  <div style="max-width:560px;margin:0 auto;padding:32px 20px;">
    <div style="font-size:14px;font-weight:700;color:#A78BFA;letter-spacing:0.04em;margin-bottom:20px;">ASSESS PULSE</div>
    <h1 style="font-size:22px;margin:0 0 12px;color:#E8EDF5;">You're invited to complete an assessment</h1>
    <p style="font-size:14px;line-height:1.55;color:#9AA8BC;margin:0 0 20px;">
      <strong style="color:#E8EDF5;">{company}</strong> has invited
      <strong style="color:#E8EDF5;">{name}</strong> to complete
      <strong style="color:#E8EDF5;">{title}</strong>.
    </p>
    <p style="font-size:14px;line-height:1.55;color:#9AA8BC;margin:0 0 8px;">Your access code:</p>
    <div style="margin:0 0 24px;padding:14px 16px;background:#111827;border:1px solid #2A3344;border-radius:8px;font-family:ui-monospace,Consolas,monospace;font-size:18px;color:#A78BFA;letter-spacing:0.06em;">
      {code}
    </div>
    <a href="{link}" style="display:inline-block;padding:12px 20px;background:#6B4CE8;color:#F5F3FF;text-decoration:none;border-radius:8px;font-weight:700;font-size:14px;">
      Start assessment
    </a>
    <div style="margin-top:28px;padding-top:16px;border-top:1px solid #2A3344;">
      <p style="font-size:13px;line-height:1.5;color:#9AA8BC;margin:0 0 8px;"><strong style="color:#E8EDF5;">Guidelines</strong></p>
      <ul style="margin:0;padding-left:18px;color:#9AA8BC;font-size:13px;line-height:1.55;">
        <li>Find a quiet place with a stable internet connection.</li>
        <li>Your answers autosave — you can leave and return with the same code.</li>
        <li>Complete each section in one sitting when possible.</li>
      </ul>
    </div>
    <p style="font-size:12px;color:#64748b;margin-top:28px;">If the button doesn't work, paste this link into your browser:<br>{link}</p>
  </div>
</body></html>"""


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
    return f"""<!DOCTYPE html>
<html><body style="margin:0;padding:0;background:#0B0F17;color:#E8EDF5;font-family:Segoe UI,Helvetica,Arial,sans-serif;">
  <div style="max-width:560px;margin:0 auto;padding:32px 20px;">
    <div style="font-size:14px;font-weight:700;color:#A78BFA;letter-spacing:0.04em;margin-bottom:20px;">ASSESS PULSE</div>
    <h1 style="font-size:22px;margin:0 0 12px;color:#E8EDF5;">Candidate completed assessment</h1>
    <p style="font-size:14px;line-height:1.55;color:#9AA8BC;margin:0 0 16px;">
      Hello <strong style="color:#E8EDF5;">{greeting}</strong>,
      <strong style="color:#E8EDF5;">{cand}</strong> ({email}) has finished
      <strong style="color:#E8EDF5;">{title}</strong>.
    </p>
    <p style="font-size:14px;line-height:1.55;color:#9AA8BC;margin:0 0 20px;">
      Their report is ready to download from the HR Tracker. JD fit scoring may still be finishing in the background.
    </p>
    <div style="margin:0 0 8px;padding:14px 16px;background:#111827;border:1px solid #2A3344;border-radius:8px;font-size:13px;color:#9AA8BC;">
      Open <strong style="color:#E8EDF5;">Assess Pulse → HR Tracker</strong> and download the report for this candidate.
    </div>
    <p style="font-size:12px;color:#64748b;margin-top:28px;">This is an automated notification from Assess Pulse.</p>
  </div>
</body></html>"""


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
    return f"""<!DOCTYPE html>
<html><body style="margin:0;padding:0;background:#0B0F17;color:#E8EDF5;font-family:Segoe UI,Helvetica,Arial,sans-serif;">
  <div style="max-width:560px;margin:0 auto;padding:32px 20px;">
    <div style="font-size:14px;font-weight:700;color:#A78BFA;letter-spacing:0.04em;margin-bottom:20px;">ASSESS PULSE</div>
    <h1 style="font-size:22px;margin:0 0 12px;color:#E8EDF5;">Friendly reminder</h1>
    <p style="font-size:14px;line-height:1.55;color:#9AA8BC;margin:0 0 16px;">
      Hello <strong style="color:#E8EDF5;">{name}</strong>, please finish your
      <strong style="color:#E8EDF5;">{title}</strong> assessment when you can.
    </p>
    <div style="margin:0 0 24px;padding:14px 16px;background:#111827;border:1px solid #2A3344;border-radius:8px;font-family:ui-monospace,Consolas,monospace;font-size:18px;color:#A78BFA;">
      {code}
    </div>
    <a href="{link}" style="display:inline-block;padding:12px 18px;background:#6B4CE8;color:#F5F3FF;text-decoration:none;border-radius:8px;font-weight:700;font-size:14px;">
      Continue assessment
    </a>
  </div>
</body></html>"""


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
    section = "margin:0 0 20px;padding:16px;background:#111827;border:1px solid #2A3344;border-radius:8px;"
    label = "font-size:11px;font-weight:700;letter-spacing:0.08em;color:#60A5FA;margin:0 0 10px;"
    body = "font-size:13px;line-height:1.55;color:#9AA8BC;margin:0 0 12px;"
    mono = "font-family:ui-monospace,Consolas,monospace;"
    button = (
        "display:inline-block;padding:10px 16px;background:#2563EB;color:#FFFFFF;"
        "text-decoration:none;border-radius:8px;font-weight:700;font-size:13px;"
    )
    return f"""<!DOCTYPE html>
<html><body style="margin:0;padding:0;background:#0B0F17;color:#E8EDF5;font-family:Segoe UI,Helvetica,Arial,sans-serif;">
  <div style="max-width:560px;margin:0 auto;padding:32px 20px;">
    <div style="font-size:14px;font-weight:700;color:#60A5FA;letter-spacing:0.04em;margin-bottom:20px;">ASSESS PULSE</div>
    <h1 style="font-size:22px;margin:0 0 12px;color:#E8EDF5;">{title} is ready to share</h1>
    <p style="font-size:14px;line-height:1.55;color:#9AA8BC;margin:0 0 24px;">
      Hello <strong style="color:#E8EDF5;">{company}</strong>, your assessment is live.
      Forward the candidate details below to applicants, and use the HR portal to track results.
    </p>

    <div style="{section}">
      <p style="{label}">CANDIDATE ACCESS</p>
      <p style="{body}">Candidates open this link and enter the PIN with their name and email.</p>
      <p style="font-size:12px;color:#9AA8BC;margin:0 0 4px;">Test link</p>
      <p style="{mono}font-size:13px;color:#E8EDF5;margin:0 0 12px;word-break:break-all;">
        <a href="{candidate_link}" style="color:#93C5FD;">{candidate_link}</a>
      </p>
      <p style="font-size:12px;color:#9AA8BC;margin:0 0 4px;">PIN</p>
      <p style="{mono}font-size:18px;color:#93C5FD;letter-spacing:0.06em;margin:0;">{code}</p>
    </div>

    <div style="{section}">
      <p style="{label}">HR PORTAL ACCESS</p>
      <p style="{body}">Sign in to follow candidate progress and download reports.</p>
      <a href="{hr_link}" style="{button}">Open HR portal</a>
      <p style="{mono}font-size:12px;color:#64748b;margin:12px 0 0;word-break:break-all;">{hr_link}</p>
    </div>

    <p style="font-size:12px;color:#64748b;margin-top:28px;">This message was sent by Assess Pulse on behalf of your account team.</p>
  </div>
</body></html>"""


def admin_otp_message(otp: str) -> str:
    """Plain-text body of the admin sign-in code email.

    Args:
        otp: Six-digit verification code.

    Returns:
        The sentence delivered to the admin inbox.
    """
    return f"Your MindQ Admin Verification Code is: {otp}. Valid for 5 minutes."


def render_admin_otp_html(otp: str) -> str:
    """HTML wrapper for the admin sign-in code. The code is escaped.

    Args:
        otp: Six-digit verification code.

    Returns:
        HTML document whose visible sentence is ``admin_otp_message``.
    """
    message = html.escape(admin_otp_message(otp))
    return f"""<!DOCTYPE html>
<html><body style="margin:0;padding:0;background:#0B0F17;color:#E8EDF5;font-family:Segoe UI,Helvetica,Arial,sans-serif;">
  <div style="max-width:560px;margin:0 auto;padding:32px 20px;">
    <p style="font-size:16px;line-height:1.5;margin:0 0 16px;">{message}</p>
    <p style="font-size:13px;line-height:1.5;color:#9AA8BC;margin:0;">If you did not try to sign in, you can ignore this email.</p>
  </div>
</body></html>"""


# Opt-in labels only. "development" is the Settings default, so it must not
# count: existing deploys set DEBUG=false and never set ENVIRONMENT.
_OTP_LOG_FALLBACK_ENVIRONMENTS = frozenset({"qa", "staging", "test"})


def _otp_log_fallback_enabled() -> bool:
    """True only for local debug or an explicit QA/staging environment.

    Fail closed. ``DEBUG=false`` is the production contract, and
    ``assert_production_ready`` does not require ``ENVIRONMENT``. The default
    ``development`` value therefore must not swallow SES failures or write a
    live admin OTP to logs. ``settings.is_production`` disables the fallback
    even when DEBUG is on.

    Returns:
        Whether a failed admin OTP email may be logged and swallowed.
    """
    if settings.is_production:
        return False
    environment = (settings.ENVIRONMENT or "").strip().lower()
    if environment in _OTP_LOG_FALLBACK_ENVIRONMENTS:
        return True
    return bool(settings.DEBUG)


def _log_admin_otp_fallback(to_email: str, otp: str, exc: BaseException) -> None:
    """Log a prominent banner carrying the OTP after an SES failure (QA only).

    Args:
        to_email: Admin inbox the code was meant for.
        otp: Six-digit verification code.
        exc: SES / mailer failure that triggered the fallback.
    """
    banner = "\n".join(
        [
            "",
            "=" * 70,
            "  !!!  SES DELIVERY FAILED - QA/STAGING OTP FALLBACK  !!!",
            "  (DEBUG or ENVIRONMENT=qa|staging|test - never in production)",
            "=" * 70,
            f"  Recipient : {to_email}",
            f"  OTP CODE  : {otp}",
            f"  Error     : {type(exc).__name__}: {exc}",
            "  Action    : enter the OTP code above on the admin login screen.",
            "=" * 70,
            "",
        ]
    )
    logger.warning(banner)


async def send_admin_otp_email(to_email: str, otp: str) -> None:
    """Deliver an admin sign-in code through the configured transactional mailer.

    ``ENVIRONMENT=production``, and ``DEBUG=false`` unless ``ENVIRONMENT`` is
    explicitly qa, staging, or test: delivery failures raise so the caller
    can discard the challenge instead of issuing a temp token nobody can
    complete. The default ``ENVIRONMENT=development`` does not enable logging.

    Explicit QA/staging (``ENVIRONMENT`` of qa, staging, or test) and local
    ``DEBUG=true``: SES failures (e.g. sandbox ``MessageRejected`` for an
    unverified recipient) are caught, the code is logged in a prominent
    banner for testers, and the function returns successfully so the
    ``admin_login_challenges`` transaction is committed, not rolled back.

    Args:
        to_email: Admin inbox that just passed the password check.
        otp: Six-digit verification code.

    Raises:
        RuntimeError: In production, when the mailer is not configured or
            rejected the message.
    """
    try:
        result = await send_transactional_email_async(
            to_email,
            "Your MindQ Admin Verification Code",
            render_admin_otp_html(otp),
            raise_on_error=True,
        )
        if not result:
            raise RuntimeError("Verification email was not sent")
    except Exception as exc:  # noqa: BLE001 - re-raised in production below
        if _otp_log_fallback_enabled():
            logger.exception(
                "Admin OTP SES delivery failed; using QA log fallback to=%s",
                to_email,
            )
            _log_admin_otp_fallback(to_email, otp, exc)
            return
        if isinstance(exc, RuntimeError):
            raise
        raise RuntimeError(f"Verification email was not sent: {exc}") from exc
