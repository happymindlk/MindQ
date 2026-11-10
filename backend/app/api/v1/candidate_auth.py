"""Candidate OTP authentication: SES code send + verify (no Supabase OTP)."""
from typing import NoReturn
import logging

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import issue_candidate_token
from app.database import get_db
from app.exceptions import PackageClosedError, PackageNotOpenError
from app.schemas.candidate import (
    CandidateAuthOtpSendRequest,
    CandidateAuthOtpVerifyRequest,
    CandidateOtpChallengeResponse,
    CandidateResponse,
)
from app.security import (
    candidate_otp_limiter,
    candidate_otp_verify_limiter,
    enforce_rate_limit,
    login_limiter,
)
from app.services.candidate_otp import (
    CandidateOtpError,
    request_candidate_otp,
    verify_candidate_challenge,
)
from app.services.candidate_service import CandidateService

logger = logging.getLogger("app.candidate_auth")

router = APIRouter()


def _raise_package_window(exc: Exception) -> NoReturn:
    """Map package login-window failures to the candidate-facing 403 shape."""
    if isinstance(exc, (PackageNotOpenError, PackageClosedError)):
        raise HTTPException(
            status_code=403, detail={"code": exc.code, "message": exc.detail}
        ) from exc
    raise exc


@router.post("/otp/send", response_model=CandidateOtpChallengeResponse)
async def send_candidate_otp(
    body: CandidateAuthOtpSendRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Email a one-time code for the submitted access code + identity.

    Names are validated here for contract parity with verify; the challenge
    itself binds only email + access code (via the signed temp token), and
    names are re-submitted at verify where the candidate row is written.

    Args:
        body: Candidate email, access code, and display names.
        request: Incoming request (rate-limited per IP).
        db: Async database session.

    Returns:
        ``otp_required`` plus the temp token required at verify.
    """
    enforce_rate_limit(candidate_otp_limiter, request, "candidate_otp_send")
    try:
        return await request_candidate_otp(db, body.access_code, str(body.email))
    except CandidateOtpError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
    except (PackageNotOpenError, PackageClosedError) as exc:
        _raise_package_window(exc)


@router.post("/otp/verify", response_model=CandidateResponse)
async def verify_candidate_otp(
    body: CandidateAuthOtpVerifyRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Verify an OTP challenge and return the candidate session directly.

    Consumes the challenge, creates or loads the candidate, and mints the
    candidate JWT — there is no separate login exchange. Invite emails are
    sent only via explicit HR/ops invite endpoints (not on first login).

    Args:
        body: Candidate identity, temp token, and six-digit code.
        request: Incoming request (rate-limited per IP).
        db: Async database session.

    Returns:
        Candidate record with a freshly minted candidate token.
    """
    enforce_rate_limit(login_limiter, request, "candidate_login")
    enforce_rate_limit(candidate_otp_verify_limiter, request, "candidate_otp_verify")
    try:
        await verify_candidate_challenge(
            db,
            temp_token=body.temp_token,
            otp_code=body.otp_code,
            email=str(body.email),
            access_code=body.access_code,
        )
    except CandidateOtpError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
    try:
        candidate, is_new = await CandidateService.login(db, body)
    except (PackageNotOpenError, PackageClosedError) as exc:
        _raise_package_window(exc)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    candidate.token = issue_candidate_token(candidate)
    logger.info(
        "candidate_login",
        extra={
            "event": "candidate_login",
            "request_id": getattr(request.state, "request_id", None),
            "candidate_id": str(candidate.id),
            "package_id": str(candidate.package_id),
            "is_new": is_new,
        },
    )
    return candidate
