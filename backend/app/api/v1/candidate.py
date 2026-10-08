from uuid import UUID
from typing import NoReturn
import logging
from fastapi import APIRouter, BackgroundTasks, Depends, Header, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.database import get_db
from app.models.candidate import Candidate
from app.models.corporate import Corporate
from app.schemas.candidate import (
    CandidateLogin,
    CandidateResponse,
    CandidateTestResponse,
)
from app.schemas.response import ResponseSave, ResponseSubmit
from app.services.candidate_service import CandidateService
from app.services.package_service import PackageService
from app.services.email_service import EmailService
from app.services.background import score_ai_for_candidate
from app.services.runner_payload import build_runner_payload
from app.auth import issue_candidate_token, get_current_candidate, verify_candidate_email_otp
from app.config import settings
from app.exceptions import (
    AssessmentAlreadySubmittedError,
    AssessmentNotFoundError,
    AssessmentTimeExpiredError,
)
from app.security import enforce_rate_limit, login_limiter

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
    raise exc


@router.post("/login", response_model=CandidateResponse)
async def login(
    login_data: CandidateLogin,
    background_tasks: BackgroundTasks,
    request: Request,
    authorization: str | None = Header(None),
    db: AsyncSession = Depends(get_db),
):
    """Exchange an access code plus a verified email OTP for a candidate JWT.

    Args:
        login_data: Access code and candidate identity.
        background_tasks: Queue for the first-login invite email.
        request: Incoming request (rate-limited per IP).
        authorization: ``Bearer <Supabase OTP access token>`` for ``login_data.email``.
        db: Async database session.

    Returns:
        Candidate record with a freshly minted candidate token.
    """
    enforce_rate_limit(login_limiter, request, "candidate_login")
    if settings.CANDIDATE_OTP_REQUIRED:
        verify_candidate_email_otp(authorization, str(login_data.email))
    try:
        candidate, is_new = await CandidateService.login(db, login_data)
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
    except (AssessmentNotFoundError, AssessmentAlreadySubmittedError) as exc:
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
    except (AssessmentNotFoundError, AssessmentAlreadySubmittedError) as exc:
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
    return {
        "assessment_id": str(progress.assessment_id),
        "status": progress.status,
        "score": float(progress.score) if progress.score is not None else None,
        "completed_at": progress.completed_at,
        "jd_scoring_queued": package_complete,
    }
