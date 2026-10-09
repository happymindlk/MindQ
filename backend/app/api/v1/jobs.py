"""Scheduled maintenance jobs (invoke via cron / Task Scheduler against this API)."""
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import HRUserContext, get_current_hr_user
from app.config import settings
from app.database import get_db
from app.models.assessment import Assessment
from app.models.candidate import Candidate
from app.models.candidate_progress import CandidateProgress
from app.models.package import Package
from app.services.email_service import EmailService

router = APIRouter()


@router.post("/nudge-due")
async def nudge_candidates_due(
    hr: HRUserContext = Depends(get_current_hr_user),
    db: AsyncSession = Depends(get_db),
):
    """Nudge incomplete candidates whose package is older than NUDGE_AFTER_HOURS.

    Intended to be called by an external scheduler (T-24h). Scoped to the
    caller's corporate. Returns counts only — never candidate PII.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(hours=settings.NUDGE_AFTER_HOURS)
    packages = (
        await db.execute(
            select(Package).where(
                Package.corporate_id == hr.corporate_id,
                Package.is_active.is_(True),
                Package.created_at <= cutoff,
            )
        )
    ).scalars().all()

    nudged = 0
    skipped = 0
    for pkg in packages:
        total = len(
            (
                await db.execute(
                    select(Assessment.id).where(Assessment.package_id == pkg.id)
                )
            ).scalars().all()
        )
        candidates = (
            await db.execute(select(Candidate).where(Candidate.package_id == pkg.id))
        ).scalars().all()
        for cand in candidates:
            progresses = (
                await db.execute(
                    select(CandidateProgress).where(
                        CandidateProgress.candidate_id == cand.id
                    )
                )
            ).scalars().all()
            completed = sum(1 for p in progresses if p.status == "COMPLETED")
            if total > 0 and completed >= total:
                skipped += 1
                continue
            ok = await EmailService.send_nudge_email(
                cand.email, cand.full_name, cand.access_code, pkg.title
            )
            if ok:
                nudged += 1
            else:
                skipped += 1

    return {
        "nudged": nudged,
        "skipped": skipped,
        "packages_considered": len(packages),
        "after_hours": settings.NUDGE_AFTER_HOURS,
    }
