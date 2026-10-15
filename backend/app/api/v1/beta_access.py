"""Gated beta / waitlist access requests for unprovisioned HR users."""
from __future__ import annotations

import html
import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import SupabaseUserContext, get_current_supabase_user
from app.config import settings
from app.database import get_db
from app.models.corporate import Corporate
from app.models.hr_user import HRUser
from app.services.email import send_transactional_email

logger = logging.getLogger("app.beta_access")

router = APIRouter()

_DEFAULT_TEST_SLUG = "acme"
_DEFAULT_TEST_NAME = "Acme"


def _beta_request_html(user_email: str, user_id: str) -> str:
    safe_email = html.escape(user_email)
    safe_id = html.escape(user_id)
    return f"""<!DOCTYPE html>
<html>
<body style="font-family:Segoe UI,system-ui,sans-serif;line-height:1.5;color:#111827;">
  <h2 style="margin:0 0 12px;">New beta access request</h2>
  <p style="margin:0 0 16px;">An HR user requested Assess Pulse beta access. Provision their tenant via SQL using the values below.</p>
  <table style="border-collapse:collapse;font-size:14px;">
    <tr>
      <td style="padding:8px 12px;border:1px solid #e5e7eb;background:#f9fafb;font-weight:600;">Email</td>
      <td style="padding:8px 12px;border:1px solid #e5e7eb;font-family:ui-monospace,monospace;">{safe_email}</td>
    </tr>
    <tr>
      <td style="padding:8px 12px;border:1px solid #e5e7eb;background:#f9fafb;font-weight:600;">Supabase UUID</td>
      <td style="padding:8px 12px;border:1px solid #e5e7eb;font-family:ui-monospace,monospace;">{safe_id}</td>
    </tr>
  </table>
  <p style="margin:16px 0 0;font-size:13px;color:#6b7280;">
    Insert into <code>public.hr_users</code> (and create a <code>corporates</code> row if needed), then have the
    user refresh their session so the custom access token hook injects <code>app_metadata.corporate_id</code>.
  </p>
</body>
</html>"""


async def _ensure_test_corporate(db: AsyncSession) -> uuid.UUID:
    """Return the id of the local ``acme`` test tenant, creating it if missing."""
    existing = (
        await db.execute(select(Corporate.id).where(Corporate.slug == _DEFAULT_TEST_SLUG).limit(1))
    ).scalar_one_or_none()
    if existing:
        return existing

    corp = Corporate(id=uuid.uuid4(), name=_DEFAULT_TEST_NAME, slug=_DEFAULT_TEST_SLUG)
    db.add(corp)
    await db.flush()
    logger.info("Created default test corporate slug=%s id=%s", _DEFAULT_TEST_SLUG, corp.id)
    return corp.id


async def _auto_provision_hr_user(
    db: AsyncSession,
    *,
    user_id: uuid.UUID,
    email: str,
) -> uuid.UUID:
    """Link an Auth user to the Acme test tenant via ``hr_users``.

    Note: there is no ``public.users`` table — Supabase Auth owns ``auth.users``.
    The caller is already authenticated, so we only upsert tenant membership.
    """
    corporate_id = await _ensure_test_corporate(db)
    stmt = (
        pg_insert(HRUser)
        .values(
            user_id=user_id,
            corporate_id=corporate_id,
            full_name=email.split("@", 1)[0],
            role="admin",
        )
        .on_conflict_do_nothing(index_elements=["user_id"])
    )
    await db.execute(stmt)
    await db.commit()
    logger.info(
        "Auto-approved HR user user_id=%s email=%s corporate_id=%s",
        user_id,
        email,
        corporate_id,
    )
    return corporate_id


@router.post("/request-beta-access")
async def request_beta_access(
    user: SupabaseUserContext = Depends(get_current_supabase_user),
    db: AsyncSession = Depends(get_db),
):
    """Notify admin — or auto-provision designated test emails into the Acme tenant.

    Callers must be signed in via Supabase Auth but do not need a corporate
    profile yet (gated waitlist). Non-auto emails send synchronously so
    delivery errors surface as HTTP 500.
    """
    if user.corporate_id:
        return {
            "success": True,
            "ok": True,
            "already_provisioned": True,
            "auto_approved": False,
            "message": "Your workspace is already provisioned. You can open the admin console.",
            "message_id": None,
        }

    email = (user.email or "").strip()
    if not email:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Your account has no email address",
        )

    if email.lower() in settings.auto_approve_email_set:
        try:
            corporate_id = await _auto_provision_hr_user(
                db, user_id=user.user_id, email=email
            )
        except Exception as exc:  # noqa: BLE001
            logger.error("Auto-approve provisioning failed for %s: %s", email, exc, exc_info=True)
            await db.rollback()
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Auto-approve provisioning failed: {exc}",
            ) from exc
        return {
            "success": True,
            "ok": True,
            "auto_approved": True,
            "already_provisioned": False,
            "corporate_id": str(corporate_id),
            "message": "Test account auto-approved. Refreshing your workspace…",
            "message_id": None,
        }

    if not settings.resend_configured:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Access request email is not configured",
        )

    admin_to = settings.admin_notification_email
    subject = f"New Beta Access Request: {email}"
    logger.info(
        "Beta access request user_id=%s email=%s notify=%s",
        user.user_id,
        email,
        admin_to,
    )

    try:
        result = send_transactional_email(
            admin_to,
            subject,
            _beta_request_html(email, str(user.user_id)),
            raise_on_error=True,
        )
    except RuntimeError as exc:
        logger.error("Beta access email failed: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(exc),
        ) from exc

    message_id = (result or {}).get("id")
    return {
        "success": True,
        "ok": True,
        "auto_approved": False,
        "already_provisioned": False,
        "message": "Request sent. We'll email you when your workspace is ready.",
        "message_id": message_id,
    }
