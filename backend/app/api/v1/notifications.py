from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy.ext.asyncio import AsyncSession
from app.database import get_db
from app.auth import get_current_hr_user, HRUserContext, is_ops_role
from app.jobs.enqueue import enqueue_nudge_email
from app.services.candidate_service import CandidateService
from app.services.package_service import PackageService
from app.services import storage as storage_service
from app.security import email_limiter, enforce_user_rate_limit

router = APIRouter()


@router.post("/{id}/nudge")
async def nudge_candidate(
    id: UUID,
    hr: HRUserContext = Depends(get_current_hr_user),
    db: AsyncSession = Depends(get_db),
):
    """Queue a reminder email to a candidate. HR-only, tenant-scoped."""
    enforce_user_rate_limit(email_limiter, hr.user_id, "candidate_nudge")
    candidate = await CandidateService.get_candidate(db, id)
    if not candidate:
        raise HTTPException(status_code=404, detail="Candidate not found")
    # service_role bypasses RLS, so enforce tenant isolation in code.
    if candidate.corporate_id != hr.corporate_id:
        raise HTTPException(status_code=403, detail="Forbidden")

    package = await PackageService.get_package(db, candidate.package_id)
    await enqueue_nudge_email(
        candidate.email,
        candidate.full_name,
        candidate.access_code,
        package.title if package else "your assessment",
        candidate_id=candidate.id,
    )
    return {"sent": True, "queued": True, "candidate_id": str(candidate.id)}


@router.post("/{id}/reset")
async def reset_candidate_assessment(
    id: UUID,
    hr: HRUserContext = Depends(get_current_hr_user),
    db: AsyncSession = Depends(get_db),
):
    """Clear a candidate's assessment progress so they can retake from scratch.

    Ops may reset any tenant; HR is limited to their own corporate.

    Args:
        id: ``candidates.id``.
        hr: Authenticated HR or ops user.
        db: Async database session.

    Returns:
        Success payload confirming the assessment was reset.
    """
    candidate = await CandidateService.get_candidate(db, id)
    if not candidate:
        raise HTTPException(status_code=404, detail="Candidate not found")

    # service_role bypasses RLS, so enforce tenant isolation in code.
    # Ops manages every client company; HR stays in their own tenant.
    if not is_ops_role(hr.role) and candidate.corporate_id != hr.corporate_id:
        raise HTTPException(status_code=403, detail="Forbidden")

    await CandidateService.reset_assessment(db, candidate)
    storage_service.purge_cached_reports(candidate.corporate_id, candidate.id)
    return {
        "success": True,
        "message": "Candidate assessment successfully reset",
    }


@router.post("/{id}/soft-delete")
async def soft_delete_candidate(
    id: UUID,
    hr: HRUserContext = Depends(get_current_hr_user),
    db: AsyncSession = Depends(get_db),
):
    """Soft-delete a candidate so they leave active lists and exports.

    Ops-only. Historical rows (responses, progress, evaluations) remain in
    PostgreSQL with ``deleted_at`` set.

    Args:
        id: ``candidates.id``.
        hr: Authenticated user (must be ops).
        db: Async database session.

    Returns:
        Success payload confirming the candidate was soft-deleted.
    """
    if not is_ops_role(hr.role):
        raise HTTPException(status_code=403, detail="Forbidden")

    candidate = await CandidateService.get_candidate(db, id)
    if not candidate:
        raise HTTPException(status_code=404, detail="Candidate not found")

    await CandidateService.soft_delete_candidate(
        db, candidate, admin_user_id=hr.user_id
    )
    return {
        "success": True,
        "message": "Candidate successfully deleted",
    }


@router.delete("/{id}", status_code=204)
async def erase_candidate(
    id: UUID,
    hr: HRUserContext = Depends(get_current_hr_user),
    db: AsyncSession = Depends(get_db),
) -> Response:
    """Hard-delete a candidate (right to erasure), including stored reports.

    Ops may erase any tenant; HR is limited to their own corporate. Cross-tenant
    HR probes and missing ids both return 404 so existence is not leaked.

    Args:
        id: ``candidates.id``.
        hr: Authenticated HR or ops user.
        db: Async database session.

    Returns:
        Empty 204 response on success.
    """
    candidate = await CandidateService.get_candidate(db, id)
    if not candidate:
        raise HTTPException(status_code=404, detail="Candidate not found")

    if not is_ops_role(hr.role) and candidate.corporate_id != hr.corporate_id:
        # Collapse forbidden cross-tenant probes to 404 (do not confirm existence).
        raise HTTPException(status_code=404, detail="Candidate not found")

    corporate_id, candidate_id = await CandidateService.erase_candidate(
        db, candidate, admin_user_id=hr.user_id
    )
    storage_service.purge_candidate_report_files(corporate_id, candidate_id)
    return Response(status_code=204)
