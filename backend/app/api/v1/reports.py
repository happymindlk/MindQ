from uuid import UUID
import logging
from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from starlette.concurrency import run_in_threadpool
from app.database import get_db
from app.auth import get_current_hr_user, HRUserContext, is_ops_role
from app.services.candidate_service import CandidateService
from app.services.package_service import PackageService
from app.services.report_service import ReportService
from app.services import storage as storage_service
from app.models.candidate_progress import CandidateProgress
from app.models.candidate_response import CandidateResponse
from app.models.assessment import Assessment
from app.models.corporate import Corporate
from app.services.jd_scoring import JdScoringService
from app.services.technical_eval import TechnicalEvalService

router = APIRouter()
logger = logging.getLogger(__name__)


@router.get("/{id}/report")
async def generate_candidate_report(
    id: UUID,
    hr: HRUserContext = Depends(get_current_hr_user),
    db: AsyncSession = Depends(get_db),
):
    candidate = await CandidateService.get_candidate(db, id)
    if not candidate:
        raise HTTPException(status_code=404, detail="Candidate not found")

    # service_role bypasses RLS, so enforce tenant isolation in code.
    # Ops manages every client company; HR stays in their own tenant.
    if not is_ops_role(hr.role) and candidate.corporate_id != hr.corporate_id:
        raise HTTPException(status_code=403, detail="Forbidden")

    package = await PackageService.get_package(db, candidate.package_id)

    corporate = (
        await db.execute(select(Corporate).where(Corporate.id == candidate.corporate_id))
    ).scalar_one_or_none()

    progress = (
        await db.execute(select(CandidateProgress).where(CandidateProgress.candidate_id == id))
    ).scalars().all()

    assessments = (
        await db.execute(
            select(Assessment)
            .where(Assessment.package_id == candidate.package_id)
            .order_by(Assessment.position)
        )
    ).scalars().all()
    titles = {a.id: a.title for a in assessments}

    responses = (
        await db.execute(
            select(CandidateResponse).where(CandidateResponse.candidate_id == id)
        )
    ).scalars().all()

    responses_by_assessment: dict = {}
    for row in responses:
        bucket = responses_by_assessment.setdefault(row.assessment_id, {})
        bucket[str(row.question_id)] = row.response
    if TechnicalEvalService.has_missing_open_evals(
        list(assessments), responses_by_assessment
    ):
        try:
            await TechnicalEvalService.evaluate_candidate(
                db,
                candidate=candidate,
                assessments=list(assessments),
                progress_rows=list(progress),
            )
            responses = (
                await db.execute(
                    select(CandidateResponse).where(CandidateResponse.candidate_id == id)
                )
            ).scalars().all()
        except Exception:
            logger.exception(
                "admin_report_technical_eval_backfill_failed candidate_id=%s", id
            )

    results_data = [
        {
            "assessment": titles.get(p.assessment_id, str(p.assessment_id)),
            "score": float(p.score) if p.score is not None else None,
            "status": p.status,
        }
        for p in progress
    ]

    jd_eval, jd_status = await JdScoringService.get_or_evaluate(
        db,
        candidate=candidate,
        package=package,
        assessments=list(assessments),
        progresses=list(progress),
        responses=list(responses),
    )

    content, is_pdf = await run_in_threadpool(
        ReportService.generate_report_bytes,
        candidate_name=candidate.full_name,
        package_title=package.title if package else "",
        results=results_data,
        jd_fit=jd_eval.model_dump() if jd_eval else None,
        jd_status=jd_status,
        corporate_name=corporate.name if corporate else None,
        corporate_logo_url=corporate.logo_url if corporate else None,
    )

    # Best-effort archive to Supabase Storage (never blocks the download).
    await run_in_threadpool(
        storage_service.upload_report, candidate.corporate_id, candidate.id, content, is_pdf
    )

    ext = "pdf" if is_pdf else "html"
    return Response(
        content=content,
        media_type="application/pdf" if is_pdf else "text/html",
        headers={
            "Content-Disposition": f'attachment; filename="report-{id}.{ext}"',
            "X-Report-Type": "PDF" if is_pdf else "HTML",
            "X-Jd-Fit-Status": jd_status,
        },
    )
