from uuid import UUID
from typing import NoReturn
import logging
from datetime import datetime, timezone
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from app.database import get_db
from app.models.candidate import Candidate
from app.schemas.candidate import CandidateTestResponse
from app.schemas.response import ResponseSave, ResponseSubmit
from app.services.candidate_service import CandidateService, assessment_duration_seconds
from app.services.background import finalize_and_score_ai
from app.services.runner_payload import (
    build_runner_payload,
    remaining_seconds,
    write_remaining_seconds,
)
from app.auth import get_current_candidate
from app.exceptions import (
    AssessmentAlreadySubmittedError,
    AssessmentNotFoundError,
    AssessmentNotStartedError,
    AssessmentTimeExpiredError,
    PackageClosedError,
    PackageNotOpenError,
    UnknownQuestionError,
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
    if isinstance(exc, AssessmentNotStartedError):
        raise HTTPException(
            status_code=409, detail={"code": exc.code, "message": exc.detail}
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
    """Load the runner payload without starting the attempt clock.

    ``started_at`` is null until the candidate explicitly posts ``/start``
    (instruction screen → "I'm ready to begin"). Prefetch from the dashboard
    is therefore safe and will not mark modules ``IN_PROGRESS``.
    """
    try:
        assessment, progress, answers = await CandidateService.load_runner_context(
            db, candidate, assessment_id, include_answers=True
        )
    except (
        AssessmentNotFoundError,
        AssessmentAlreadySubmittedError,
        PackageNotOpenError,
        PackageClosedError,
    ) as exc:
        _raise_integrity(exc)

    started_at = getattr(progress, "started_at", None) if progress else None

    return build_runner_payload(
        assessment_id=assessment.id,
        title=assessment.title,
        description=assessment.description,
        questions=assessment.questions,
        time_limit_minutes=assessment.time_limit_minutes,
        # Same resolver the server deadline uses, so client and server agree on timing.
        duration_seconds=assessment_duration_seconds(assessment),
        timer_mode=getattr(assessment, "timer_mode", None),
        shuffle=bool(getattr(assessment, "shuffle_questions", False)),
        seed=f"{candidate.id}:{assessment.id}",
        answers=answers,
        started_at=started_at,
        module_kind=getattr(assessment, "module_kind", None),
        show_top_disclaimer=bool(getattr(assessment, "show_top_disclaimer", False)),
        top_disclaimer_text=getattr(assessment, "top_disclaimer_text", None),
        show_confidentiality_notice=bool(
            getattr(assessment, "show_confidentiality_notice", False)
        ),
        confidentiality_notice_text=getattr(assessment, "confidentiality_notice_text", None),
    )


@router.post("/test/{assessment_id}/start")
async def start_test(
    assessment_id: UUID,
    candidate: Candidate = Depends(get_current_candidate),
    db: AsyncSession = Depends(get_db),
):
    """Mark the module ``IN_PROGRESS`` and start the countdown after explicit consent."""
    try:
        assessment, progress = await CandidateService.require_writable_assessment(
            db, candidate, assessment_id, for_update=True
        )
        progress = await CandidateService.ensure_started(db, candidate, assessment, progress)
    except (
        AssessmentNotFoundError,
        AssessmentAlreadySubmittedError,
        PackageNotOpenError,
        PackageClosedError,
    ) as exc:
        _raise_integrity(exc)

    now = datetime.now(timezone.utc)
    duration = assessment_duration_seconds(assessment)
    return {
        "assessment_id": str(assessment.id),
        "status": progress.status,
        "started_at": progress.started_at,
        "remaining_seconds": remaining_seconds(
            progress.started_at,
            duration,
            now,
        ),
        "write_remaining_seconds": write_remaining_seconds(
            progress.started_at,
            duration,
            now,
        ),
    }


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
        AssessmentNotStartedError,
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
    # Core facet scoring, LLM technical eval, JD synthesis, and HR email all
    # stay off the candidate hot path.
    background_tasks.add_task(finalize_and_score_ai, candidate.id, assessment_id)
    company_name = await CandidateService.get_company_name(db, candidate)
    # Scores stay server-side: echoing them lets candidates calibrate answers
    # across modules or share keyed results.
    return {
        "assessment_id": str(progress.assessment_id),
        "status": progress.status,
        "completed_at": progress.completed_at,
        "package_complete": package_complete,
        "company_name": company_name,
        "jd_scoring_queued": True,
    }
