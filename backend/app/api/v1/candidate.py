from uuid import UUID
from typing import NoReturn
import logging
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.database import get_db
from app.models.candidate import Candidate
from app.models.corporate import Corporate
from app.schemas.candidate import (
    CandidateLogin,
    CandidateOtpChallengeResponse,
    CandidateOtpRequest,
    CandidateResponse,
    CandidateTestResponse,
)
from app.schemas.response import ResponseSave, ResponseSubmit
from app.services.candidate_service import CandidateService
from app.services.package_service import PackageService
from app.services.email import resolve_frontend_origin
from app.services.email_service import EmailService
from app.services.background import score_ai_for_candidate
from app.services.runner_payload import build_runner_payload
from app.auth import issue_candidate_token, get_current_candidate
from app.exceptions import (
    AssessmentAlreadySubmittedError,
    AssessmentNotFoundError,
    AssessmentTimeExpiredError,
    PackageClosedError,
    PackageNotOpenError,
    UnknownQuestionError,
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

logger = logging.getLogger("app.candidate")

router = APIRouter()


def _raise_integrity(exc: Exception) -> NoReturn:
    if isinstance(exc, AssessmentNotFoundError):
        raise HTTPException(status_code=404, detail="Test not found") from exc
    if isinstance(exc, AssessmentAlreadySubmittedError):
        raise HTTPException(status_code=409, detail=exc.detail) from exc
    if isinstance(exc, AssessmentTimeExpiredError):
        raise HTTPException(
            status_code=409, detail={"code": "TIME_EXPIRED", "message": exc.detail}
        ) from exc
    if isinstance(exc, (PackageNotOpenError, PackageClosedError)):
        raise HTTPException(
            status_code=403, detail={"code": exc.code, "message": exc.detail}
        ) from exc
    if isinstance(exc, UnknownQuestionError):
        raise HTTPException(
            status_code=422, detail={"code": exc.code, "message": exc.detail}
        ) from exc
    raise exc


@router.post("/otp/request", response_model=CandidateOtpChallengeResponse)
async def request_otp(
    body: CandidateOtpRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Email a one-time code for the submitted access code + email.

    The response is only ``otp_required`` and a temp token; no candidate
    session exists until the code is submitted to ``/login``. Repeating
    this call invalidates the previous code when the send cap allows it.

    Args:
        body: Access code and candidate email.
        request: Incoming request (rate-limited per IP).
        db: Async database session.

    Returns:
        Temp token to submit with the emailed code.
    """
    enforce_rate_limit(candidate_otp_limiter, request, "candidate_otp_request")
    try:
        return await request_candidate_otp(db, body.access_code, str(body.email))
    except CandidateOtpError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
    except (PackageNotOpenError, PackageClosedError) as exc:
        _raise_integrity(exc)


@router.post("/login", response_model=CandidateResponse)
async def login(
    login_data: CandidateLogin,
    background_tasks: BackgroundTasks,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Exchange an access code plus a verified email OTP for a candidate JWT.

    Args:
        login_data: Access code, candidate identity, temp token, and OTP code.
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
            temp_token=login_data.temp_token,
            otp_code=login_data.otp_code,
            email=str(login_data.email),
            access_code=login_data.access_code,
        )
    except CandidateOtpError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
    try:
        candidate, is_new = await CandidateService.login(db, login_data)
    except (PackageNotOpenError, PackageClosedError) as exc:
        _raise_integrity(exc)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
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


@router.get("/dashboard")
async def get_dashboard(
    candidate: Candidate = Depends(get_current_candidate), db: AsyncSession = Depends(get_db)
):
    return await CandidateService.get_dashboard(db, candidate)


@router.get("/test/{assessment_id}", response_model=CandidateTestResponse)
async def get_test(
    assessment_id: UUID,
    candidate: Candidate = Depends(get_current_candidate),
    db: AsyncSession = Depends(get_db),
):
    try:
        assessment, progress = await CandidateService.require_writable_assessment(
            db, candidate, assessment_id
        )
        progress = await CandidateService.ensure_started(db, candidate, assessment, progress)
        answers = await CandidateService.get_saved_answers(db, candidate.id, assessment_id)
    except (
        AssessmentNotFoundError,
        AssessmentAlreadySubmittedError,
        PackageNotOpenError,
        PackageClosedError,
    ) as exc:
        _raise_integrity(exc)
    return build_runner_payload(
        assessment_id=assessment.id,
        title=assessment.title,
        description=assessment.description,
        questions=assessment.questions,
        time_limit_minutes=assessment.time_limit_minutes,
        duration_seconds=getattr(assessment, "duration_seconds", None),
        timer_mode=getattr(assessment, "timer_mode", None),
        shuffle=bool(getattr(assessment, "shuffle_questions", False)),
        seed=f"{candidate.id}:{assessment.id}",
        answers=answers,
        started_at=getattr(progress, "started_at", None),
    )


@router.post("/autosave")
async def autosave(
    save_data: ResponseSave,
    candidate: Candidate = Depends(get_current_candidate),
    db: AsyncSession = Depends(get_db),
):
    try:
        resp = await CandidateService.autosave_response(db, candidate, save_data)
    except (
        AssessmentNotFoundError,
        AssessmentAlreadySubmittedError,
        AssessmentTimeExpiredError,
        PackageNotOpenError,
        PackageClosedError,
        UnknownQuestionError,
    ) as exc:
        _raise_integrity(exc)
    return {"id": str(resp.id), "saved_at": resp.saved_at}


@router.post("/test/{assessment_id}/submit")
async def submit_test(
    assessment_id: UUID,
    background_tasks: BackgroundTasks,
    candidate: Candidate = Depends(get_current_candidate),
    db: AsyncSession = Depends(get_db),
    body: ResponseSubmit | None = None,
):
    try:
        progress, package_complete = await CandidateService.submit_test(
            db,
            candidate,
            assessment_id,
            pending_responses=(body.responses if body else None),
            client_duration_seconds=(body.total_module_duration_seconds if body else None),
        )
    except (
        AssessmentNotFoundError,
        AssessmentAlreadySubmittedError,
        PackageNotOpenError,
        PackageClosedError,
    ) as exc:
        _raise_integrity(exc)
    # Do not block the candidate on Gemini; item eval + JD fit run in the background.
    background_tasks.add_task(score_ai_for_candidate, candidate.id, assessment_id)
    if package_complete:
        package = await PackageService.get_package(db, candidate.package_id)
        corporate = (
            await db.execute(select(Corporate).where(Corporate.id == candidate.corporate_id))
        ).scalar_one_or_none()
        if corporate and corporate.contact_email:
            background_tasks.add_task(
                EmailService.send_hr_completion_email,
                corporate.contact_email,
                candidate_name=candidate.full_name,
                candidate_email=candidate.email,
                package_title=package.title if package else "assessment package",
                hr_name=corporate.name,
            )
    # Scores stay server-side: echoing them lets candidates calibrate answers
    # across modules or share keyed results.
    return {
        "assessment_id": str(progress.assessment_id),
        "status": progress.status,
        "completed_at": progress.completed_at,
        "jd_scoring_queued": package_complete,
    }
