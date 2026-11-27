"""HR/client OTP authentication: SES code send + verify (no Supabase OTP)."""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.schemas.hr_auth import HrOtpChallengeResponse, HrOtpSendRequest, HrOtpVerifyRequest, HrTokenResponse
from app.security import (
    client_ip,
    enforce_rate_limit,
    hr_login_failure_limiter,
    hr_otp_limiter,
    hr_otp_verify_limiter,
)
from app.services.admin_otp import LOCKOUT_MINUTES
from app.services.hr_otp import HrOtpError, request_hr_otp, verify_hr_challenge

logger = logging.getLogger("app.hr_auth")

router = APIRouter()


def _otp_http(exc: HrOtpError) -> HTTPException:
    """Map OTP service errors to HTTP responses; attach Retry-After on lockouts."""
    headers = None
    if exc.status_code == 429:
        retry_after = exc.retry_after or int(LOCKOUT_MINUTES) * 60
        headers = {"Retry-After": str(max(1, int(retry_after)))}
        logger.warning(
            "hr_auth_blocked",
            extra={"event": "hr_auth_blocked", "detail": exc.detail},
        )
    return HTTPException(status_code=exc.status_code, detail=exc.detail, headers=headers)


@router.post("/otp/send", response_model=HrOtpChallengeResponse)
async def send_hr_otp(
    body: HrOtpSendRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Email a one-time code to a registered HR/client user.

    Args:
        body: Corporate email.
        request: Incoming request (rate-limited per IP).
        db: Async database session.

    Returns:
        ``otp_required`` plus the temp token required at verify.
    """
    enforce_rate_limit(hr_otp_limiter, request, "hr_otp_send")
    try:
        return await request_hr_otp(db, str(body.email))
    except HrOtpError as exc:
        raise _otp_http(exc) from exc


@router.post("/otp/verify", response_model=HrTokenResponse)
async def verify_hr_otp(
    body: HrOtpVerifyRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Verify an OTP challenge and return the backend client-portal session.

    Consumes the challenge and mints the ``client_hr`` JWT directly —
    there is no Supabase session exchange. Failed verifies are counted per
    IP (5 / minute) in addition to the challenge-row strike lockout.

    Args:
        body: Corporate email, temp token, and six-digit code.
        request: Incoming request (rate-limited per IP).
        db: Async database session.

    Returns:
        Client JWT, tenant branding, and the HR profile.
    """
    failure_key = f"hr_login:{client_ip(request)}"
    hr_login_failure_limiter.assert_allowed(failure_key)
    enforce_rate_limit(hr_otp_verify_limiter, request, "hr_otp_verify")
    try:
        result = await verify_hr_challenge(
            db,
            temp_token=body.temp_token,
            otp_code=body.otp_code,
            email=str(body.email),
        )
    except HrOtpError as exc:
        if exc.status_code in {401, 403}:
            hr_login_failure_limiter.record_failure(failure_key)
        raise _otp_http(exc) from exc
    # Failures are NOT cleared on success: they expire with the window, so one
    # valid account cannot reset the brute-force budget for a shared IP.
    return result
