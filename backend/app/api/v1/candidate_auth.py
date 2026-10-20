"""Candidate OTP authentication: SES code send + verify (no Supabase OTP)."""
from typing import NoReturn
import logging

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
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
from app.services.email import resolve_frontend_origin
from app.services.email_service import EmailService
from app.services.package_service import PackageService

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
    # #region agent log
    try:
        import json as _json
        import time as _time
        from pathlib import Path as _Path

        with open(_Path(__file__).resolve().parents[4] / "debug-605235.log", "a", encoding="utf-8") as _fh:
            _fh.write(_json.dumps({"sessionId": "605235", "runId": "pre-fix", "hypothesisId": "A,B", "location": "candidate_auth.py:send", "message": "otp send handler entered", "data": {"path": request.url.path, "method": request.method}, "timestamp": int(_time.time() * 1000)}) + "\n")
    except Exception:
        pass
    # #endregion
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
    background_tasks: BackgroundTasks,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Verify an OTP challenge and return the candidate session directly.

    Consumes the challenge, creates or loads the candidate, queues the
    first-login invite email, and mints the candidate JWT — there is no
    separate login exchange.

    Args:
        body: Candidate identity, temp token, and six-digit code.
        background_tasks: Queue for the first-login invite email.
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
    if is_new:
        package = await PackageService.get_package(db, candidate.package_id)
        background_tasks.add_task(
            EmailService.send_candidate_invite_email,
            candidate.email,
            candidate.full_name,
            candidate.access_code,
            package.title if package else "your assessment",
            origin=resolve_frontend_origin(request),
        )
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
