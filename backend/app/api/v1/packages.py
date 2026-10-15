"""Package builder + managed-service cart endpoints (ops-authenticated)."""
from __future__ import annotations

import asyncio
import logging
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import func, select
from sqlalchemy.exc import ProgrammingError
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import HRUserContext, get_current_ops_user
from app.database import get_db
from app.exceptions import schema_drift_detail
from app.models.candidate import Candidate
from app.models.corporate import Corporate
from app.models.package import Package
from app.schemas.client_package import (
    BlindReviewResponse,
    CorporateListItem,
    CorporatePackageItem,
    DraftPackageRequest,
    DraftPackageResponse,
    GlobalModuleResponse,
    PackagePreviewRequest,
    PublishPackageResponse,
    SharePackageRequest,
    SharePackageResponse,
)
from app.schemas.candidate import CandidateTestResponse
from app.schemas.library import AddTemplateRequest, AddTemplateResponse
from app.schemas.package_builder import (
    AssessmentPackageBlueprint,
    GeneratePackageRequest,
    SavePackageRequest,
    SavePackageResponse,
)
from app.security import enforce_rate_limit, public_limiter
from app.services.client_package import (
    ClientPackageError,
    ClientPackageService,
    PackageLockedError,
)
from app.services.library import LibraryConflictError, LibraryError, LibraryService
from app.services.package_share import (
    PackageShareError,
    list_corporate_packages,
    share_package,
)
from app.services.package_generator import (
    PackageGeneratorError,
    generate_package_from_jd,
    save_blueprint_package,
)
from app.services.gemini_client import overall_deadline_seconds

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("/generate", response_model=AssessmentPackageBlueprint)
async def generate_package(
    body: GeneratePackageRequest,
    hr: HRUserContext = Depends(get_current_ops_user),
):
    """Generate an assessment blueprint from a job description via Gemini.

    Args:
        body: Role, JD, seniority, and optional question count.
        hr: Authenticated HR user (tenant isolation via JWT corporate_id).

    Returns:
        Structured `AssessmentPackageBlueprint` for frontend preview.
    """
    _ = hr  # Auth gate; generation is not persisted until /save.
    try:
        blueprint = await asyncio.wait_for(
            generate_package_from_jd(
                role=body.role,
                job_description=body.job_description,
                seniority=body.seniority,
                question_count=body.question_count,
            ),
            timeout=overall_deadline_seconds(),
        )
    except asyncio.TimeoutError as exc:
        logger.error(
            "package_generate_timeout corporate_id=%s timeout_s=%s",
            hr.corporate_id,
            overall_deadline_seconds(),
        )
        raise HTTPException(
            status_code=504,
            detail="Assessment generation timed out. Try again with a shorter JD.",
        ) from exc
    except PackageGeneratorError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception(
            "package_generate_failed corporate_id=%s", hr.corporate_id
        )
        raise HTTPException(
            status_code=502,
            detail="Failed to generate assessment package.",
        ) from exc

    return blueprint


@router.post("/save", response_model=SavePackageResponse)
async def save_package(
    body: SavePackageRequest,
    hr: HRUserContext = Depends(get_current_ops_user),
    db: AsyncSession = Depends(get_db),
):
    """Persist an approved blueprint under the authenticated HR tenant.

    Creates a `packages` row and one `assessments` row with questions JSONB
    (mapped from the blueprint). Linked to `hr.corporate_id`.

    Args:
        body: Approved blueprint and original JD text.
        hr: Authenticated HR user.
        db: Async database session.

    Returns:
        Package id, access code, and counts for the success UI.
    """
    if not body.blueprint.questions:
        raise HTTPException(status_code=400, detail="Blueprint has no questions")

    try:
        package = await save_blueprint_package(
            db,
            corporate_id=hr.corporate_id,
            blueprint=body.blueprint,
            job_description=body.job_description,
        )
    except Exception as exc:
        logger.exception(
            "package_save_failed corporate_id=%s", hr.corporate_id
        )
        raise HTTPException(
            status_code=500,
            detail="Failed to save assessment package.",
        ) from exc

    return SavePackageResponse(
        id=str(package.id),
        access_code=package.access_code,
        title=package.title,
        assessment_count=1,
        question_count=len(body.blueprint.questions),
    )


@router.get("/modules", response_model=list[GlobalModuleResponse])
async def list_global_modules(
    db: AsyncSession = Depends(get_db),
    _: HRUserContext = Depends(get_current_ops_user),
):
    """Return the searchable global module catalog (ops only)."""
    return await ClientPackageService.list_modules(db)


@router.post("/preview", response_model=list[CandidateTestResponse])
async def preview_package(
    body: PackagePreviewRequest,
    db: AsyncSession = Depends(get_db),
    _: HRUserContext = Depends(get_current_ops_user),
):
    """Render an unsaved composer sequence exactly as candidates would see it.

    Uses the same sanitizer as ``GET /candidate/test`` so preview can never show
    keys, weights, or SME rationale that a real candidate would not receive.
    """
    try:
        return await ClientPackageService.preview(db, body)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ClientPackageError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/corporates", response_model=list[CorporateListItem])
async def list_corporates_for_ops(
    db: AsyncSession = Depends(get_db),
    _: HRUserContext = Depends(get_current_ops_user),
):
    """Company picker for the cart and Assessment History tier 1."""
    pkg_count = (
        select(Package.corporate_id, func.count(Package.id).label("pkg_count"))
        .where(
            (Package.status == "published") | (Package.is_active.is_(True))
        )
        .group_by(Package.corporate_id)
        .subquery()
    )
    cand_count = (
        select(Candidate.corporate_id, func.count(Candidate.id).label("cand_count"))
        .group_by(Candidate.corporate_id)
        .subquery()
    )
    result = await db.execute(
        select(
            Corporate,
            func.coalesce(pkg_count.c.pkg_count, 0),
            func.coalesce(cand_count.c.cand_count, 0),
        )
        .outerjoin(pkg_count, pkg_count.c.corporate_id == Corporate.id)
        .outerjoin(cand_count, cand_count.c.corporate_id == Corporate.id)
        .order_by(Corporate.name)
    )
    items: list[CorporateListItem] = []
    for corp, packages_n, candidates_n in result.all():
        items.append(
            CorporateListItem(
                id=corp.id,
                name=corp.name,
                slug=corp.slug,
                contact_email=corp.contact_email,
                logo_url=corp.logo_url,
                package_count=int(packages_n or 0),
                candidate_count=int(candidates_n or 0),
                created_at=corp.created_at,
            )
        )
    return items


@router.get("/drafts/{package_id}", response_model=DraftPackageResponse)
async def get_draft_package(
    package_id: UUID,
    db: AsyncSession = Depends(get_db),
    _: HRUserContext = Depends(get_current_ops_user),
):
    """Load a draft or published cart for the package builder."""
    try:
        return await ClientPackageService.get_draft(db, package_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/drafts", response_model=DraftPackageResponse)
async def create_draft_package(
    body: DraftPackageRequest,
    db: AsyncSession = Depends(get_db),
    _: HRUserContext = Depends(get_current_ops_user),
):
    """Create a draft client package (status=draft, unpublished)."""
    try:
        return await ClientPackageService.save_draft(db, body)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except PackageLockedError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ClientPackageError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except ProgrammingError as exc:
        raise HTTPException(status_code=503, detail=schema_drift_detail(exc)) from exc


@router.put("/drafts/{package_id}", response_model=DraftPackageResponse)
async def update_draft_package(
    package_id: UUID,
    body: DraftPackageRequest,
    db: AsyncSession = Depends(get_db),
    _: HRUserContext = Depends(get_current_ops_user),
):
    """Replace a draft cart. Published packages return 409."""
    try:
        return await ClientPackageService.save_draft(db, body, package_id=package_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except PackageLockedError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ClientPackageError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except ProgrammingError as exc:
        raise HTTPException(status_code=503, detail=schema_drift_detail(exc)) from exc


@router.post("/drafts/{package_id}/publish", response_model=PublishPackageResponse)
async def publish_draft_package(
    package_id: UUID,
    db: AsyncSession = Depends(get_db),
    _: HRUserContext = Depends(get_current_ops_user),
):
    """Lock the cart and mint review / candidate sharing paths."""
    try:
        return await ClientPackageService.publish(db, package_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except PackageLockedError as extra:
        raise HTTPException(status_code=409, detail=str(extra)) from extra
    except ClientPackageError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post(
    "/{package_id}/add-template",
    response_model=AddTemplateResponse,
    status_code=201,
)
async def add_template_to_package(
    package_id: UUID,
    body: AddTemplateRequest,
    db: AsyncSession = Depends(get_db),
    _: HRUserContext = Depends(get_current_ops_user),
):
    """Fork a Master Library template into a package cart with an eager snapshot.

    Copies active template_questions into package_modules.questions so later
    master edits never alter this package.
    """
    try:
        return await LibraryService.add_template_to_package(
            db, package_id, body.template_id
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except PackageLockedError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except LibraryConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except LibraryError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("", response_model=list[CorporatePackageItem])
async def list_packages_for_corporate(
    corporate_id: UUID = Query(..., description="Corporate whose packages to list"),
    db: AsyncSession = Depends(get_db),
    _: HRUserContext = Depends(get_current_ops_user),
):
    """Corporate history: packages with invited / completed counts and share links.

    Args:
        corporate_id: Target corporate UUID.
        db: Async database session.
        _: Authenticated ops user.

    Returns:
        The corporate's packages, newest first.
    """
    try:
        return await list_corporate_packages(db, corporate_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


_SHARE_ERROR_STATUS: dict[str, int] = {
    "not_published": 409,
    "no_recipient": 422,
    "delivery_failed": 502,
}


@router.post("/{package_id}/share", response_model=SharePackageResponse)
async def share_package_endpoint(
    package_id: UUID,
    body: SharePackageRequest | None = None,
    db: AsyncSession = Depends(get_db),
    _: HRUserContext = Depends(get_current_ops_user),
):
    """Email candidate access (link + PIN) and HR portal access for a published package.

    Args:
        package_id: Target package UUID.
        body: Optional recipient override; defaults to the corporate HR email.
        db: Async database session.
        _: Authenticated ops user.

    Returns:
        ``{success, sent_to, candidate_link, access_code, hr_login_link}``.
    """
    recipient = body.recipient_email if body else None
    try:
        return await share_package(db, package_id, recipient)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except PackageShareError as exc:
        raise HTTPException(
            status_code=_SHARE_ERROR_STATUS.get(exc.code, 400), detail=str(exc)
        ) from exc


@router.get("/review/{review_token}", response_model=BlindReviewResponse)
async def get_blind_review(
    review_token: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Token-gated HR review. Psychometric modules are stripped server-side."""
    enforce_rate_limit(public_limiter, request, "blind_review_get")
    try:
        return await ClientPackageService.get_blind_review(db, review_token)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
