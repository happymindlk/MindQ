"""Admin login: password, then a one-time email code, then the Supabase session."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import HRUserContext, get_current_ops_user
from app.database import get_db
from app.schemas.admin_auth import (
    AdminChangePasswordRequest,
    AdminChangePasswordResponse,
    AdminForgotPasswordRequest,
    AdminForgotPasswordResponse,
    AdminLoginChallengeResponse,
    AdminLoginRequest,
    AdminTokenResponse,
    AdminVerifyOtpRequest,
)
from app.security import (
    admin_forgot_password_limiter,
    admin_otp_limiter,
    admin_otp_verify_limiter,
    enforce_rate_limit,
)
from app.services.admin_otp import AdminLoginError, start_admin_login, verify_admin_otp
from app.services.admin_password import (
    AdminPasswordError,
    change_admin_password,
    request_admin_password_reset,
)

router = APIRouter()


def _http(exc: AdminLoginError) -> HTTPException:
    return HTTPException(status_code=exc.status_code, detail=exc.detail)


def _password_http(exc: AdminPasswordError) -> HTTPException:
    return HTTPException(status_code=exc.status_code, detail=exc.detail)


def _bearer_token(authorization: str | None) -> str:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="Missing bearer token")
    token = authorization.split(" ", 1)[1].strip()
    if not token:
        raise HTTPException(status_code=401, detail="Missing bearer token")
    return token


@router.post("/login", response_model=AdminLoginChallengeResponse)
async def admin_login(
    body: AdminLoginRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Check admin credentials and email a five-minute code.

    A successful password does not return an admin JWT. The response is only
    ``otp_required`` and a temp token. Repeating this call invalidates the
    previous code when the send cap allows another email; it is not safe to
    retry as a no-op.

    Args:
        body: Email and password.
        request: Incoming request, rate-limited per IP.
        db: Async database session.

    Returns:
        Temp token to submit with the emailed code.
    """
    enforce_rate_limit(admin_otp_limiter, request, "admin_otp_login")
    try:
        return await start_admin_login(db, str(body.email), body.password.get_secret_value())
    except AdminLoginError as exc:
        raise _http(exc) from exc


@router.post("/verify-otp", response_model=AdminTokenResponse)
async def admin_verify_otp(
    body: AdminVerifyOtpRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Exchange a temp token and a one-time code for the admin session.

    Three wrong codes lock the sign-in for 15 minutes. A correct code works once.

    Args:
        body: Temp token and six-digit code.
        request: Incoming request, rate-limited per IP.
        db: Async database session.

    Returns:
        Supabase access token, refresh token, and the ops profile.
    """
    enforce_rate_limit(admin_otp_verify_limiter, request, "admin_otp_verify")
    try:
        return await verify_admin_otp(db, body.temp_token, body.otp_code)
    except AdminLoginError as exc:
        raise _http(exc) from exc


@router.post("/forgot-password", response_model=AdminForgotPasswordResponse)
async def admin_forgot_password(
    body: AdminForgotPasswordRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Request a password-reset email for an ops admin account.

    The response is always the same confirmation string so callers cannot
    enumerate which addresses have admin membership. When the email matches
    an ops user, Auth Admin mints a recovery link and SES delivers it.

    Args:
        body: Admin email address.
        request: Incoming request, rate-limited per IP.
        db: Async database session.

    Returns:
        Enumeration-safe confirmation message.
    """
    enforce_rate_limit(admin_forgot_password_limiter, request, "admin_forgot_password")
    detail = await request_admin_password_reset(db, str(body.email))
    return AdminForgotPasswordResponse(detail=detail)


@router.post("/change-password", response_model=AdminChangePasswordResponse)
async def admin_change_password(
    body: AdminChangePasswordRequest,
    authorization: str | None = Header(None),
    ops: HRUserContext = Depends(get_current_ops_user),
):
    """Change the signed-in admin password after verifying the current one.

    On success, existing refresh tokens are revoked (global logout) so other
    devices must sign in again with the new password.

    Args:
        body: Current and new passwords.
        authorization: Bearer token for the active session (used to revoke).
        ops: Authenticated ops user.

    Returns:
        Confirmation detail.
    """
    access_token = _bearer_token(authorization)
    try:
        await change_admin_password(
            ops,
            current_password=body.current_password.get_secret_value(),
            new_password=body.new_password.get_secret_value(),
            access_token=access_token,
        )
    except AdminPasswordError as exc:
        raise _password_http(exc) from exc
    return AdminChangePasswordResponse()
