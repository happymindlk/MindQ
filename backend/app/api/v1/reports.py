from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
from app.database import get_db
from app.auth import get_current_hr_user, HRUserContext, is_ops_role
from app.api.v1.candidate_reports import build_technical_report_data
from app.services.audit_log import log_report_accessed
from app.services.candidate_service import CandidateService
from app.services.report_pdf import report_content_disposition, serve_report_pdf
from app.security import enforce_user_rate_limit, report_limiter

router = APIRouter()

__all__ = ["router", "report_content_disposition"]


@router.get("/{id}/report")
async def generate_candidate_report(
    id: UUID,
    hr: HRUserContext = Depends(get_current_hr_user),
    db: AsyncSession = Depends(get_db),
) -> StreamingResponse:
    """Download the MindQ Report PDF for HR or ops.

    Args:
        id: ``candidates.id``.
        hr: Authenticated HR or ops user.
        db: Async database session.

    Returns:
        PDF (or HTML fallback) attachment from the shared report PDF service.
    """
    # WeasyPrint rendering is CPU-heavy; Gemini work is queued on ARQ, not awaited.
    enforce_user_rate_limit(report_limiter, hr.user_id, "report_pdf")
    candidate = await CandidateService.get_candidate(db, id)
    if not candidate:
        raise HTTPException(status_code=404, detail="Candidate not found")

    # service_role bypasses RLS, so enforce tenant isolation in code.
    # Ops manages every client company; HR stays in their own tenant.
    if not is_ops_role(hr.role) and candidate.corporate_id != hr.corporate_id:
        raise HTTPException(status_code=403, detail="Forbidden")

    report = await build_technical_report_data(db, candidate)
    log_report_accessed(
        actor_id=hr.user_id,
        actor_role=hr.role,
        corporate_id=candidate.corporate_id,
        candidate_id=candidate.id,
        format="pdf",
    )
    return await serve_report_pdf(
        report,
        corporate_id=candidate.corporate_id,
        candidate_id=candidate.id,
        portal="admin",
    )
