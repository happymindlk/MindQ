"""Admin self-serve password reset and authenticated password change."""
from __future__ import annotations

import logging

from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import HRUserContext
from app.services.email import resolve_frontend_origin, send_admin_password_reset_email
from app.services.hr_membership import find_ops_role_for_email
from app.services.supabase_admin import (
    SupabaseAdminError,
    generate_password_recovery_link,
    update_user_password,
)
from app.services.supabase_password import (
    SupabaseAuthUnavailable,
    revoke_supabase_session,
    verify_supabase_password,
)

logger = logging.getLogger("app.admin_auth")

RESET_CONFIRMATION = (
    "If an account exists for this email, a reset link has been sent."
)


class AdminPasswordError(Exception):
    """Domain error for admin password change / reset flows."""

    def __init__(self, detail: str, *, status_code: int = 400):
        super().__init__(detail)
        self.detail = detail
        self.status_code = status_code


async def request_admin_password_reset(db: AsyncSession, email: str) -> str:
    """Send a recovery email when ``email`` belongs to an ops admin.

    Always returns the same confirmation string so callers cannot enumerate
    which addresses have admin accounts. Delivery failures for known admins
    are logged; the public response stays generic.

    Args:
        db: Async database session.
        email: Submitted address (already normalized by the schema).

    Returns:
        Generic confirmation copy for the UI.
    """
    normalized = (email or "").strip().lower()
    if not normalized:
        return RESET_CONFIRMATION

    try:
        role = await find_ops_role_for_email(db, normalized)
    except Exception:  # noqa: BLE001 - enumeration-safe; never leak DB errors
        logger.exception(
            "admin_password_reset_lookup_failed",
            extra={"event": "admin_password_reset_lookup_failed"},
        )
        return RESET_CONFIRMATION

    if not role:
        return RESET_CONFIRMATION

    redirect_to = f"{resolve_frontend_origin()}/admin/reset-password"
    try:
        action_link = generate_password_recovery_link(normalized, redirect_to)
        await send_admin_password_reset_email(normalized, action_link)
    except (SupabaseAdminError, RuntimeError, SupabaseAuthUnavailable) as exc:
        logger.error(
            "admin_password_reset_send_failed",
            extra={
                "event": "admin_password_reset_send_failed",
                "error_type": type(exc).__name__,
            },
        )
    except Exception:  # noqa: BLE001
        logger.exception(
            "admin_password_reset_unexpected",
            extra={"event": "admin_password_reset_unexpected"},
        )
    return RESET_CONFIRMATION


async def change_admin_password(
    ops: HRUserContext,
    *,
    current_password: str,
    new_password: str,
    access_token: str,
) -> None:
    """Verify the current password, set a new one, and revoke other sessions.

    Args:
        ops: Authenticated ops user from the Supabase JWT.
        current_password: Plain password the user claims is current.
        new_password: Replacement password (min length enforced by schema).
        access_token: Bearer token from this request — used for global logout.

    Raises:
        AdminPasswordError: Current password is wrong, Auth is down, or update fails.
    """
    email = (ops.email or "").strip().lower()
    if not email:
        raise AdminPasswordError("Signed-in email is required.", status_code=400)

    try:
        session = await verify_supabase_password(email, current_password)
    except SupabaseAuthUnavailable as exc:
        raise AdminPasswordError(
            "Authentication service is unavailable.", status_code=503
        ) from exc

    if session is None:
        raise AdminPasswordError("Incorrect current password.", status_code=400)

    # Drop the verification grant immediately — it is not the caller's session.
    await revoke_supabase_session(session.access_token, scope="local")

    if session.user_id != ops.user_id:
        raise AdminPasswordError("Incorrect current password.", status_code=400)

    try:
        update_user_password(ops.user_id, new_password)
    except SupabaseAdminError as exc:
        raise AdminPasswordError(str(exc) or "Could not update password.", status_code=400) from exc

    # Drop other devices' refresh tokens; keep this tab signed in.
    # ``others`` is supported by modern GoTrue; older stacks may no-op.
    await revoke_supabase_session(access_token, scope="others")
