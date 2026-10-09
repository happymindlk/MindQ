"""HR client portal: OTP session exchange, dashboard, scorecards, blind review.

Every authenticated route depends on ``get_current_client_user``, so only
backend-minted ``client_hr`` JWTs are accepted and every query is scoped to the
token's ``corporate_id``. Ops (Supabase) tokens are rejected here by design.
"""
from __future__ import annotations

import logging
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
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
from app.database import get_db
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
    TechnicalReportData,
)
from app.security import enforce_rate_limit, login_limiter, public_limiter
from app.services.client_package import ClientPackageService

logger = logging.getLogger("app.client")

router = APIRouter()


@router.post("/auth/session", response_model=ClientSessionResponse)
async def create_client_session(
    request: Request,
    user: SupabaseUserContext = Depends(get_current_supabase_user),
    db: AsyncSession = Depends(get_db),
):
    """Exchange a verified Supabase OTP session for a client-portal JWT.

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
    try:
        return await ClientPackageService.get_client_scorecard(
            db, candidate_id, client.corporate_id
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ProgrammingError as exc:
        logger.exception("Client scorecard retrieval failed: %s", str(exc))
        raise HTTPException(status_code=503, detail=schema_drift_detail(exc)) from exc


@router.get("/candidates/{candidate_id}/report-data", response_model=TechnicalReportData)
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
    return await build_technical_report_data(db, candidate)


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
