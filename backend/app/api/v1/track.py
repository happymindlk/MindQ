from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
import logging

from app.database import get_db
from app.models.candidate import Candidate
from app.models.corporate import Corporate
from app.models.package import Package
from app.schemas.support import PublicTrackCandidate, PublicTrackResponse
from app.security import enforce_rate_limit, public_limiter
from app.services.progress_summary import (
    ProgressSummary,
    assessment_counts,
    progress_summaries,
)

#: Public board row cap (unauthenticated endpoint; bounded memory/DB work).
TRACK_MAX_ROWS = 500

logger = logging.getLogger("app.track")

router = APIRouter()


@router.get("/{secret}", response_model=PublicTrackResponse)
async def public_package_track(
    secret: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    limit: int = Query(TRACK_MAX_ROWS, ge=1, le=TRACK_MAX_ROWS),
    offset: int = Query(0, ge=0),
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

    total_assessments = (await assessment_counts(db, [package.id])).get(package.id, 0)

    candidates = (
        await db.execute(
            select(Candidate)
            .where(
                Candidate.package_id == package.id,
                Candidate.deleted_at.is_(None),
            )
            .order_by(Candidate.created_at.desc(), Candidate.id)
            .limit(limit)
            .offset(offset)
        )
    ).scalars().all()
    summaries = await progress_summaries(db, [c.id for c in candidates])

    rows: list[PublicTrackCandidate] = []
    for cand in candidates:
        summary = summaries.get(cand.id, ProgressSummary())
        completed = summary.completed
        status = "not_started"
        if total_assessments > 0 and completed >= total_assessments:
            status = "completed"
        elif completed > 0 or cand.logged_in_at:
            status = "in_progress"

        rows.append(
            PublicTrackCandidate(
                full_name=cand.full_name,
                status=status,
                progress=f"{completed}/{total_assessments}",
                avg_score=(
                    round(summary.avg_score, 1) if summary.avg_score is not None else None
                ),
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
