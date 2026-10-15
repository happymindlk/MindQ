"""Admin login: password, then a one-time email code, then the Supabase session."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.schemas.admin_auth import (
    AdminLoginChallengeResponse,
    AdminLoginRequest,
    AdminTokenResponse,
    AdminVerifyOtpRequest,
)
from app.security import admin_otp_limiter, admin_otp_verify_limiter, enforce_rate_limit
from app.services.admin_otp import AdminLoginError, start_admin_login, verify_admin_otp

router = APIRouter()


def _http(exc: AdminLoginError) -> HTTPException:
    return HTTPException(status_code=exc.status_code, detail=exc.detail)


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
