from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
import logging

from app.database import get_db
from app.models.assessment import Assessment
from app.models.candidate import Candidate
from app.models.candidate_evaluation import CandidateEvaluation
from app.models.candidate_progress import CandidateProgress
from app.models.corporate import Corporate
from app.models.package import Package
from app.schemas.support import PublicTrackCandidate, PublicTrackResponse
from app.security import enforce_rate_limit, public_limiter

logger = logging.getLogger("app.track")

router = APIRouter()


@router.get("/{secret}", response_model=PublicTrackResponse)
async def public_package_track(
    secret: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Read-only completion board for a package, keyed by track_secret (no auth)."""
    enforce_rate_limit(public_limiter, request, "public_track")
    if not secret or len(secret) < 16:
        raise HTTPException(status_code=404, detail="Tracker not found")

    package = (
        await db.execute(select(Package).where(Package.track_secret == secret))
    ).scalars().first()
    if not package or not package.is_active:
        raise HTTPException(status_code=404, detail="Tracker not found")

    corporate = (
        await db.execute(select(Corporate).where(Corporate.id == package.corporate_id))
    ).scalars().first()

    total_assessments = len(
        (
            await db.execute(
                select(Assessment.id).where(Assessment.package_id == package.id)
            )
        ).scalars().all()
    )

    candidates = (
        await db.execute(
            select(Candidate)
            .where(Candidate.package_id == package.id)
            .order_by(Candidate.created_at.desc())
        )
    ).scalars().all()

    rows: list[PublicTrackCandidate] = []
    for cand in candidates:
        progresses = (
            await db.execute(
                select(CandidateProgress).where(CandidateProgress.candidate_id == cand.id)
            )
        ).scalars().all()
        completed = sum(1 for p in progresses if p.status == "COMPLETED")
        scores = [float(p.score) for p in progresses if p.score is not None]
        status = "not_started"
        if total_assessments > 0 and completed >= total_assessments:
            status = "completed"
        elif completed > 0 or cand.logged_in_at:
            status = "in_progress"

        eval_row = (
            await db.execute(
                select(CandidateEvaluation).where(
                    CandidateEvaluation.candidate_id == cand.id
                )
            )
        ).scalars().first()

        rows.append(
            PublicTrackCandidate(
                full_name=cand.full_name,
                status=status,
                progress=f"{completed}/{total_assessments}",
                avg_score=round(sum(scores) / len(scores), 1) if scores else None,
                jd_fit=float(eval_row.overall_fit) if eval_row and eval_row.overall_fit is not None else None,
            )
        )

    logger.info(
        "public_track_view",
        extra={
            "event": "public_track_view",
            "request_id": getattr(request.state, "request_id", None),
            "package_id": str(package.id),
            "candidate_count": len(rows),
        },
    )
    return PublicTrackResponse(
        package_title=package.title,
        corporate_name=corporate.name if corporate else None,
        candidates=rows,
    )
