"""HR client portal: OTP session exchange, dashboard, scorecards, blind review.

Every authenticated route depends on ``get_current_client_user``, so only
backend-minted ``client_hr`` JWTs are accepted and every query is scoped to the
token's ``corporate_id``. Ops (Supabase) tokens are rejected here by design.
"""
from __future__ import annotations

import asyncio
import logging
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.exc import ProgrammingError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.candidate_reports import build_technical_report_data
from app.auth import (
    ClientUserContext,
    SupabaseUserContext,
    get_current_client_user,
    get_current_supabase_user,
    is_ops_role,
    issue_client_token,
)
from app.services.audit_log import log_report_accessed
from app.database import SessionLocal, get_db
from app.exceptions import schema_drift_detail
from app.models.candidate import Candidate
from app.models.corporate import Corporate
from app.models.hr_user import HRUser
from app.schemas.client_package import (
    BlindReviewApproveResponse,
    ClientCorporate,
    ClientDashboardResponse,
    ClientPipelineRow,
    ClientScorecardResponse,
    ClientSessionResponse,
)
from app.schemas.mindq_report import MindQReportResponse
from app.security import (
    enforce_rate_limit,
    enforce_user_rate_limit,
    login_limiter,
    public_limiter,
    report_limiter,
    report_view_limiter,
    reports_zip_limiter,
)
from app.services.client_package import ClientPackageService
from app.services.report_pdf import render_report, report_filename, serve_report_pdf
from app.services.report_zip import (
    ZIP_RENDER_CONCURRENCY,
    ZipReportEntry,
    iter_reports_zip,
    unique_zip_filename,
    zip_content_disposition,
)

logger = logging.getLogger("app.client")

router = APIRouter()


@router.post("/auth/session", response_model=ClientSessionResponse)
async def create_client_session(
    request: Request,
    user: SupabaseUserContext = Depends(get_current_supabase_user),
    db: AsyncSession = Depends(get_db),
):
    """Legacy exchange of a verified Supabase session for a client-portal JWT.

    Superseded by ``POST /api/v1/hr/auth/otp/verify``, which verifies the
    SES-delivered code and mints the client JWT in one step. Retained for
    backward compatibility with already-deployed clients.

    Tenancy comes from ``hr_users`` (source of truth), not from JWT claims,
    so a stale or forged ``app_metadata.corporate_id`` cannot widen access.

    Args:
        request: Incoming request (rate-limited per IP).
        user: Supabase identity proven by the OTP verification.
        db: Async database session.

    Returns:
        Client JWT plus the tenant's name and logo.
    """
    enforce_rate_limit(login_limiter, request, "client_session")
    membership = (
        await db.execute(select(HRUser).where(HRUser.user_id == user.user_id))
    ).scalar_one_or_none()
    if membership is None:
        raise HTTPException(
            status_code=403, detail="This email is not registered for the client portal"
        )
    if is_ops_role(membership.role):
        raise HTTPException(
            status_code=403, detail="Operations accounts must use the admin portal"
        )

    corporate = (
        await db.execute(select(Corporate).where(Corporate.id == membership.corporate_id))
    ).scalar_one_or_none()
    if corporate is None:
        raise HTTPException(status_code=403, detail="Company not found")

    token, expires_in = issue_client_token(user.user_id, corporate.id, user.email)
    logger.info(
        "client_session_issued",
        extra={
            "event": "client_session_issued",
            "corporate_id": str(corporate.id),
            "request_id": getattr(request.state, "request_id", None),
        },
    )
    return ClientSessionResponse(
        access_token=token,
        expires_in=expires_in,
        corporate=ClientCorporate(
            id=corporate.id, name=corporate.name, logo_url=corporate.logo_url
        ),
    )


@router.get("/dashboard", response_model=ClientDashboardResponse)
async def client_dashboard(
    client: ClientUserContext = Depends(get_current_client_user),
    db: AsyncSession = Depends(get_db),
):
    """Published packages with candidate progress for the caller's tenant.

    Args:
        client: Verified client JWT identity.
        db: Async database session.

    Returns:
        Corporate branding and package-grouped candidate metrics.
    """
    try:
        return await ClientPackageService.get_client_dashboard(db, client.corporate_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ProgrammingError as exc:
        logger.exception("Client dashboard retrieval failed: %s", str(exc))
        raise HTTPException(status_code=503, detail=schema_drift_detail(exc)) from exc


@router.get("/pipeline", response_model=list[ClientPipelineRow])
@router.get("/candidates", response_model=list[ClientPipelineRow])
async def client_pipeline(
    client: ClientUserContext = Depends(get_current_client_user),
    db: AsyncSession = Depends(get_db),
):
    """Sanitized flat candidate pipeline for the authenticated HR tenant.

    Args:
        client: Verified client JWT identity.
        db: Async database session.

    Returns:
        Pending / Scoring / Completed rows. No psychometric item data.
    """
    try:
        return await ClientPackageService.list_client_pipeline(db, client.corporate_id)
    except ProgrammingError as exc:
        logger.exception("Client pipeline retrieval failed: %s", str(exc))
        raise HTTPException(status_code=503, detail=schema_drift_detail(exc)) from exc


@router.get("/candidates/{candidate_id}/scorecard", response_model=ClientScorecardResponse)
async def client_scorecard(
    candidate_id: UUID,
    client: ClientUserContext = Depends(get_current_client_user),
    db: AsyncSession = Depends(get_db),
):
    """Gemini scorecard with psychometric modules filtered out.

    Args:
        candidate_id: Candidate belonging to the caller's tenant.
        client: Verified client JWT identity.
        db: Async database session.

    Returns:
        Technical assessments + overall JD-fit fields only.
    """
    enforce_user_rate_limit(report_limiter, client.user_id, "client_scorecard")
    try:
        return await ClientPackageService.get_client_scorecard(
            db, candidate_id, client.corporate_id
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ProgrammingError as exc:
        logger.exception("Client scorecard retrieval failed: %s", str(exc))
        raise HTTPException(status_code=503, detail=schema_drift_detail(exc)) from exc


@router.get("/candidates/{candidate_id}/report-data", response_model=MindQReportResponse)
async def client_report_data(
    candidate_id: UUID,
    client: ClientUserContext = Depends(get_current_client_user),
    db: AsyncSession = Depends(get_db),
):
    """MindQ Report payload, tenant-scoped.

    Cross-tenant ids return 404 (not 403) so callers cannot probe whether a
    candidate exists in another tenant.

    Args:
        candidate_id: Candidate belonging to the caller's tenant.
        client: Verified client JWT identity.
        db: Async database session.

    Returns:
        Report data with module-level psychometric scores only (no item data).
    """
    enforce_user_rate_limit(report_view_limiter, client.user_id, "client_report_data")
    candidate = await _tenant_candidate(db, client, candidate_id)
    report = await build_technical_report_data(db, candidate)
    log_report_accessed(
        actor_id=client.user_id,
        actor_role=client.role,
        corporate_id=candidate.corporate_id,
        candidate_id=candidate.id,
        format="json",
    )
    return report


@router.get("/candidates/{candidate_id}/report")
async def client_report_pdf(
    candidate_id: UUID,
    client: ClientUserContext = Depends(get_current_client_user),
    db: AsyncSession = Depends(get_db),
) -> StreamingResponse:
    """Download the MindQ Report PDF, rendered and cached exactly as for admins.

    Args:
        candidate_id: Candidate belonging to the caller's tenant.
        client: Verified client JWT identity.
        db: Async database session.

    Returns:
        PDF (or HTML fallback) attachment with ``X-Report-Cache``.
    """
    enforce_user_rate_limit(report_limiter, client.user_id, "client_report_pdf")
    candidate = await _tenant_candidate(db, client, candidate_id)
    report = await build_technical_report_data(db, candidate)
    log_report_accessed(
        actor_id=client.user_id,
        actor_role=client.role,
        corporate_id=candidate.corporate_id,
        candidate_id=candidate.id,
        format="pdf",
    )
    return await serve_report_pdf(
        report,
        corporate_id=candidate.corporate_id,
        candidate_id=candidate.id,
        portal="client",
    )


@router.get("/packages/{package_id}/reports-zip")
async def client_package_reports_zip(
    package_id: UUID,
    client: ClientUserContext = Depends(get_current_client_user),
    db: AsyncSession = Depends(get_db),
) -> StreamingResponse:
    """Download every completed MindQ Report in a package as one ZIP.

    Uses the shared WeasyPrint + storage cache path for each candidate so the
    ZIP bytes match single-report downloads. One request counts against the
    bulk ZIP limiter — not once per PDF — so HR can export a round without
    exhausting the single-report budget.

    Args:
        package_id: Published package belonging to the caller's tenant.
        client: Verified client JWT identity.
        db: Async database session.

    Returns:
        ``application/zip`` attachment with ``X-Report-Zip-Count``.
    """
    enforce_user_rate_limit(reports_zip_limiter, client.user_id, "client_reports_zip")
    try:
        package, candidates = await ClientPackageService.get_package_completed_candidates(
            db, package_id, client.corporate_id
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ProgrammingError as exc:
        logger.exception("Client package reports ZIP lookup failed: %s", str(exc))
        raise HTTPException(status_code=503, detail=schema_drift_detail(exc)) from exc

    if not candidates:
        raise HTTPException(status_code=404, detail="No completed reports to download")

    # Bound WeasyPrint concurrency; each worker uses its own DB session so
    # AsyncSession is never shared across concurrent tasks.
    sem = asyncio.Semaphore(ZIP_RENDER_CONCURRENCY)
    used_names: set[str] = set()
    name_lock = asyncio.Lock()

    async def _render_entry(candidate: Candidate) -> ZipReportEntry | None:
        async with sem:
            try:
                async with SessionLocal() as session:
                    report = await build_technical_report_data(session, candidate)
                    rendered = await render_report(
                        report,
                        corporate_id=candidate.corporate_id,
                        candidate_id=candidate.id,
                        portal="client",
                    )
                ext = "pdf" if rendered.is_pdf else "html"
                desired = report_filename(
                    report.candidate_full_name or candidate.full_name, ext
                )
                async with name_lock:
                    name = unique_zip_filename(desired, used_names)
                return ZipReportEntry(filename=name, content=rendered.content)
            except Exception:
                logger.exception(
                    "client_reports_zip_entry_failed package_id=%s candidate_id=%s",
                    package_id,
                    candidate.id,
                )
                return None

    results = await asyncio.gather(*[_render_entry(c) for c in candidates])
    entries = [entry for entry in results if entry is not None]
    failures = [
        (c.full_name or str(c.id))
        for c, entry in zip(candidates, results, strict=True)
        if entry is None
    ]

    if not entries:
        raise HTTPException(status_code=502, detail="No reports could be generated")

    logger.info(
        "client_reports_zip_served package_id=%s succeeded=%s failed=%s",
        package_id,
        len(entries),
        len(failures),
    )
    return StreamingResponse(
        iter_reports_zip(entries),
        media_type="application/zip",
        headers={
            "Content-Disposition": zip_content_disposition(package.title),
            "Access-Control-Expose-Headers": (
                "Content-Disposition, X-Report-Zip-Count, X-Report-Zip-Failed"
            ),
            "X-Report-Zip-Count": str(len(entries)),
            "X-Report-Zip-Failed": str(len(failures)),
            "Cache-Control": "private, no-store",
        },
    )


async def _tenant_candidate(
    db: AsyncSession, client: ClientUserContext, candidate_id: UUID
) -> Candidate:
    """Load a candidate only if it belongs to the caller's tenant.

    The tenant filter is part of the query, so another tenant's candidate is
    indistinguishable from a missing one: both return 404, never 403, and
    callers cannot probe which candidate ids exist elsewhere.

    Args:
        db: Async database session.
        client: Verified client JWT identity (tenant-locked).
        candidate_id: Requested candidate.

    Returns:
        The candidate row.

    Raises:
        HTTPException: 404 when the candidate is missing or in another tenant.
    """
    candidate = (
        await db.execute(
            select(Candidate).where(
                Candidate.id == candidate_id,
                Candidate.corporate_id == client.corporate_id,
            )
        )
    ).scalar_one_or_none()
    if candidate is None:
        raise HTTPException(status_code=404, detail="Candidate not found")
    return candidate


@router.post(
    "/review/{review_token}/approve",
    response_model=BlindReviewApproveResponse,
)
async def approve_blind_review(
    review_token: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Token-gated HR approval. No JWT — matches the public review link.

    Args:
        review_token: Opaque package token minted at publish.
        request: Incoming request (rate-limited).
        db: Async database session.

    Returns:
        Success acknowledgement. Idempotent if already approved.
    """
    enforce_rate_limit(public_limiter, request, "blind_review_approve")
    try:
        payload = await ClientPackageService.approve_blind_review(db, review_token)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    logger.info(
        "blind_review_approved",
        extra={
            "event": "blind_review_approved",
            "request_id": getattr(request.state, "request_id", None),
        },
    )
    return BlindReviewApproveResponse(**payload)
