"""Transactional email via Resend.

Provides a sync, BackgroundTasks-safe sender plus HTML templates for candidate
invite and HR completion notifications. Never raises to callers — failures are
logged and return None.
"""
from __future__ import annotations

import functools
import html
import logging
from typing import Any
from urllib.parse import quote, urlparse

from starlette.concurrency import run_in_threadpool

from app.config import settings

logger = logging.getLogger("app.email")


def frontend_origin() -> str:
    """Public origin of the React app, without a trailing slash."""
    explicit = (settings.FRONTEND_URL or "").rstrip("/")
    if explicit:
        return explicit
    portal = (settings.PORTAL_URL or "").rstrip("/")
    if portal.endswith("/portal"):
        return portal[: -len("/portal")]
    parsed = urlparse(portal)
    if parsed.scheme and parsed.netloc:
        return f"{parsed.scheme}://{parsed.netloc}"
    return "http://localhost:5173"


def _assessment_invite_link(access_code: str) -> str:
    """Candidate CTA: `{FRONTEND_URL}/assessment?code={access_code}`."""
    return f"{frontend_origin()}/assessment?code={quote(str(access_code))}"


def _portal_link(access_code: str) -> str:
    return _assessment_invite_link(access_code)


def candidate_portal_link(access_code: str) -> str:
    """Universal candidate link that pre-fills the access code on the portal login.

    Args:
        access_code: Package access code (doubles as the candidate PIN).

    Returns:
        Absolute URL ``{FRONTEND}/portal?code={access_code}``.
    """
    return f"{frontend_origin()}/portal?code={quote(str(access_code))}"


def hr_portal_login_link() -> str:
    """Absolute URL of the HR client portal login.

    Returns:
        ``{FRONTEND}/client/login``.
    """
    return f"{frontend_origin()}/client/login"


def send_transactional_email(
    to_email: str,
    subject: str,
    html_content: str,
    *,
    raise_on_error: bool = False,
) -> dict | None:
    """Send one HTML email through Resend.

    Args:
        to_email: Recipient address.
        subject: Message subject line.
        html_content: Full HTML body.
        raise_on_error: When True, propagate Resend failures as RuntimeError
            instead of returning None (used by beta-access where the UI must
            reflect delivery errors).

    Returns:
        Resend API response dict (includes `id`) on success, otherwise None
        when ``raise_on_error`` is False.
    """
    if not settings.resend_configured:
        msg = f"Resend not configured; skipping email to {to_email} subject={subject!r}"
        logger.warning(msg)
        if raise_on_error:
            raise RuntimeError("Resend is not configured (RESEND_API_KEY missing)")
        return None

    from_addr = settings.EMAIL_FROM
    payload = {
        "from": from_addr,
        "to": [to_email],
        "subject": subject,
        "html": html_content,
    }
    logger.info(
        "Resend send starting to=%s from=%s subject=%r",
        to_email,
        from_addr,
        subject,
    )
    if "onboarding@resend.dev" in (from_addr or "").lower():
        logger.info(
            "Resend sandbox from-address in use; recipient must be the verified "
            "Resend account owner email or delivery will be rejected."
        )

    try:
        import resend

        resend.api_key = settings.RESEND_API_KEY
        result = resend.Emails.send(payload)
        # SDK may return a dict or an object with .id
        if isinstance(result, dict):
            message_id = result.get("id")
            response_payload: dict[str, Any] = result
        else:
            message_id = getattr(result, "id", None)
            response_payload = {"id": message_id}
        logger.info(
            "Resend send ok to=%s id=%s response=%s",
            to_email,
            message_id,
            response_payload,
        )
        return response_payload
    except Exception as exc:  # noqa: BLE001
        logger.error(
            "Resend send FAILED to=%s from=%s subject=%r error=%s",
            to_email,
            from_addr,
            subject,
            exc,
            exc_info=True,
        )
        if raise_on_error:
            raise RuntimeError(f"Resend rejected the email: {exc}") from exc
        return None


async def send_transactional_email_async(
    to_email: str,
    subject: str,
    html_content: str,
    *,
    raise_on_error: bool = False,
) -> dict | None:
    """Async wrapper around the sync Resend call (threadpool)."""
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
) -> str:
    """HTML for the candidate assessment invite / magic-link email."""
    name = html.escape(candidate_name or "there")
    title = html.escape(package_title or "your assessment")
    company = html.escape((corporate_name or "").strip() or "Your hiring team")
    code = html.escape(access_code)
    link = html.escape(_assessment_invite_link(access_code))
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
) -> str:
    """HTML reminder for an incomplete candidate."""
    name = html.escape(candidate_name or "there")
    title = html.escape(package_title or "your assessment")
    code = html.escape(access_code)
    link = html.escape(_portal_link(access_code))
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
) -> str:
    """HTML handing a client both candidate access and HR portal access for a package.

    Args:
        corporate_name: Client company display name.
        package_title: Published package title.
        access_code: Package access code, shown to candidates as the PIN.

    Returns:
        Full HTML document for Resend.
    """
    company = html.escape((corporate_name or "").strip() or "your team")
    title = html.escape(package_title or "your assessment")
    code = html.escape(access_code)
    candidate_link = html.escape(candidate_portal_link(access_code))
    hr_link = html.escape(hr_portal_login_link())
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
