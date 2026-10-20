"""HR/client OTP authentication: SES code send + verify (no Supabase OTP)."""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.schemas.hr_auth import HrOtpChallengeResponse, HrOtpSendRequest, HrOtpVerifyRequest, HrTokenResponse
from app.security import enforce_rate_limit, hr_otp_limiter, hr_otp_verify_limiter
from app.services.hr_otp import HrOtpError, request_hr_otp, verify_hr_challenge

logger = logging.getLogger("app.hr_auth")

router = APIRouter()


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
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc


@router.post("/otp/verify", response_model=HrTokenResponse)
async def verify_hr_otp(
    body: HrOtpVerifyRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Verify an OTP challenge and return the backend client-portal session.

    Consumes the challenge and mints the ``client_hr`` JWT directly —
    there is no Supabase session exchange.

    Args:
        body: Corporate email, temp token, and six-digit code.
        request: Incoming request (rate-limited per IP).
        db: Async database session.

    Returns:
        Client JWT, tenant branding, and the HR profile.
    """
    enforce_rate_limit(hr_otp_verify_limiter, request, "hr_otp_verify")
    try:
        return await verify_hr_challenge(
            db,
            temp_token=body.temp_token,
            otp_code=body.otp_code,
            email=str(body.email),
        )
    except HrOtpError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
