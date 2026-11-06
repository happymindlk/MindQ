from uuid import UUID
from typing import NoReturn, Any
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from app.database import get_db
from app.models.candidate import Candidate
from app.schemas.candidate import CandidateTestResponse
from app.schemas.response import ResponseSave, ResponseSubmit
from app.services.candidate_service import CandidateService, _assessment_duration
from app.services.background import finalize_and_score_ai
from app.services.runner_payload import build_runner_payload
from app.auth import get_current_candidate
from app.exceptions import (
    AssessmentAlreadySubmittedError,
    AssessmentNotFoundError,
    AssessmentTimeExpiredError,
    PackageClosedError,
    PackageNotOpenError,
    UnknownQuestionError,
)

logger = logging.getLogger("app.candidate")

router = APIRouter()


def _agent_debug_log(
    hypothesis_id: str,
    location: str,
    message: str,
    data: dict[str, Any],
) -> None:
    # #region agent log
    try:
        payload = {
            "sessionId": "5f236f",
            "runId": "pre-fix",
            "hypothesisId": hypothesis_id,
            "location": location,
            "message": message,
            "data": data,
            "timestamp": int(datetime.now(timezone.utc).timestamp() * 1000),
        }
        path = Path(r"d:\happy-mind-psychometrics\.cursor\debug-5f236f.log")
        with path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(payload, default=str) + "\n")
    except Exception:
        pass
    # #endregion


def _server_remaining_seconds(started_at: datetime | None, duration_seconds: int | None) -> int | None:
    if not duration_seconds:
        return None
    if started_at is None:
        return int(duration_seconds)
    now_utc = datetime.now(timezone.utc)
    started = started_at if started_at.tzinfo is not None else started_at.replace(tzinfo=timezone.utc)
    elapsed = (now_utc - started).total_seconds()
    return max(0, int(duration_seconds - elapsed))


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
        assessment, progress = await CandidateService.require_writable_assessment(
            db, candidate, assessment_id
        )
        answers = await CandidateService.get_saved_answers(db, candidate.id, assessment_id)
    except (
        AssessmentNotFoundError,
        AssessmentAlreadySubmittedError,
        PackageNotOpenError,
        PackageClosedError,
    ) as exc:
        _raise_integrity(exc)

    started_at = getattr(progress, "started_at", None) if progress else None
    duration = _assessment_duration(assessment)
    remaining = _server_remaining_seconds(started_at, duration)
    # #region agent log
    _agent_debug_log(
        "A",
        "candidate.py:get_test",
        "GET test payload timing fields",
        {
            "candidate_id": str(candidate.id),
            "assessment_id": str(assessment_id),
            "status": getattr(progress, "status", None) if progress else None,
            "started_at": started_at.isoformat() if started_at else None,
            "started_at_tzinfo": str(getattr(started_at, "tzinfo", None)) if started_at else None,
            "duration_seconds": duration,
            "server_remaining_seconds": remaining,
            "now_utc": datetime.now(timezone.utc).isoformat(),
        },
    )
    # #endregion

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

    duration = _assessment_duration(assessment)
    remaining = _server_remaining_seconds(progress.started_at, duration)
    # #region agent log
    _agent_debug_log(
        "E",
        "candidate.py:start_test",
        "POST start response timing fields",
        {
            "candidate_id": str(candidate.id),
            "assessment_id": str(assessment.id),
            "status": progress.status,
            "started_at": progress.started_at.isoformat() if progress.started_at else None,
            "started_at_tzinfo": str(getattr(progress.started_at, "tzinfo", None))
            if progress.started_at
            else None,
            "duration_seconds": duration,
            "server_remaining_seconds": remaining,
            "now_utc": datetime.now(timezone.utc).isoformat(),
        },
    )
    # #endregion

    return {
        "assessment_id": str(assessment.id),
        "status": progress.status,
        "started_at": progress.started_at,
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
    # Core facet scoring already ran in the submit transaction. LLM technical
    # eval, JD synthesis, and HR email stay off the candidate hot path.
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
