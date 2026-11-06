from uuid import UUID
import io
import logging
import re
from urllib.parse import quote
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import run_in_threadpool
from app.database import get_db
from app.auth import get_current_hr_user, HRUserContext, is_ops_role
from app.api.v1.candidate_reports import build_technical_report_data
from app.services.candidate_service import CandidateService
from app.services.report_service import ReportService
from app.services import storage as storage_service
from app.security import enforce_user_rate_limit, report_limiter

router = APIRouter()
logger = logging.getLogger(__name__)

REPORT_FILE_PREFIX = "MindQ Report"
_ILLEGAL_FILENAME_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]+')


def report_content_disposition(candidate_name: str | None, ext: str) -> str:
    """Build ``Content-Disposition`` for ``MindQ Report - {name}.{ext}``.

    Args:
        candidate_name: Candidate full name (untrusted; may be non-Latin).
        ext: File extension without the dot.

    Returns:
        Header value with an ASCII fallback and an RFC 5987 UTF-8 filename.
    """
    cleaned = " ".join(_ILLEGAL_FILENAME_CHARS.sub(" ", candidate_name or "").split())
    cleaned = cleaned.rstrip(". ")[:120].strip() or "Candidate"
    ascii_cleaned = " ".join(cleaned.encode("ascii", "ignore").decode("ascii").split()) or "Candidate"
    filename = f"{REPORT_FILE_PREFIX} - {cleaned}.{ext}"
    ascii_filename = f"{REPORT_FILE_PREFIX} - {ascii_cleaned}.{ext}"
    return f'attachment; filename="{ascii_filename}"; filename*=UTF-8\'\'{quote(filename)}'


@router.get("/{id}/report")
async def generate_candidate_report(
    id: UUID,
    hr: HRUserContext = Depends(get_current_hr_user),
    db: AsyncSession = Depends(get_db),
):
    # Each download can trigger Gemini backfills + WeasyPrint rendering.
    enforce_user_rate_limit(report_limiter, hr.user_id, "report_pdf")
    candidate = await CandidateService.get_candidate(db, id)
    if not candidate:
        raise HTTPException(status_code=404, detail="Candidate not found")

    # service_role bypasses RLS, so enforce tenant isolation in code.
    # Ops manages every client company; HR stays in their own tenant.
    if not is_ops_role(hr.role) and candidate.corporate_id != hr.corporate_id:
        raise HTTPException(status_code=403, detail="Forbidden")

    report = await build_technical_report_data(db, candidate)

    content, is_pdf = await run_in_threadpool(
        ReportService.generate_report_bytes,
        report=report.model_dump(mode="json"),
    )

    # Best-effort archive to Supabase Storage (never blocks the download).
    # Cold or misconfigured storage must not break the browser download path.
    try:
        await run_in_threadpool(
            storage_service.upload_report, candidate.corporate_id, candidate.id, content, is_pdf
        )
    except Exception:
        logger.exception(
            "report_storage_archive_failed candidate_id=%s", candidate.id
        )

    ext = "pdf" if is_pdf else "html"
    media_type = "application/pdf" if is_pdf else "text/html"
    return StreamingResponse(
        io.BytesIO(content),
        media_type=media_type,
        headers={
            "Content-Disposition": report_content_disposition(report.candidate_full_name, ext),
            "Access-Control-Expose-Headers": (
                "Content-Disposition, X-Report-Type, X-Report-Synthesis-Status"
            ),
            "X-Report-Type": "PDF" if is_pdf else "HTML",
            "X-Report-Synthesis-Status": report.synthesis_status,
        },
    )
