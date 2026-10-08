from uuid import UUID
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from app.database import get_db
from app.auth import get_current_hr_user, HRUserContext
from app.services.candidate_service import CandidateService
from app.services.package_service import PackageService
from app.services.email_service import EmailService

router = APIRouter()


@router.post("/{id}/nudge")
async def nudge_candidate(
    id: UUID,
    background_tasks: BackgroundTasks,
    hr: HRUserContext = Depends(get_current_hr_user),
    db: AsyncSession = Depends(get_db),
):
    """Queue a reminder email to a candidate. HR-only, tenant-scoped."""
    candidate = await CandidateService.get_candidate(db, id)
    if not candidate:
        raise HTTPException(status_code=404, detail="Candidate not found")
    # service_role bypasses RLS, so enforce tenant isolation in code.
    if candidate.corporate_id != hr.corporate_id:
        raise HTTPException(status_code=403, detail="Forbidden")

    package = await PackageService.get_package(db, candidate.package_id)
    background_tasks.add_task(
        EmailService.send_nudge_email,
        candidate.email,
        candidate.full_name,
        candidate.access_code,
        package.title if package else "your assessment",
    )
    return {"sent": True, "queued": True, "candidate_id": str(candidate.id)}
