"""Ops admin company + single-package endpoints."""
from __future__ import annotations

import logging
from uuid import UUID

from starlette.concurrency import run_in_threadpool
from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from sqlalchemy import select, text
from sqlalchemy.exc import ProgrammingError
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import HRUserContext, get_current_ops_user
from app.database import get_db
from app.exceptions import schema_drift_detail
from app.models.corporate import Corporate
from app.schemas.client_package import (
    AdminCandidateOverviewRow,
    AdminCandidateScorecard,
    AdminCorporateBrandingUpdate,
    AdminCorporateRow,
    AdminPackageOverviewRow,
    AdminPackageDetail,
    AdminPackageUpdateRequest,
    CompanyCreateRequest,
    CompanyCreateResponse,
    CompanyLogoResponse,
    CompanyUpdateRequest,
    HrInviteRequest,
    HrInviteResponse,
    PackageDeleteResponse,
    PackageScheduleResponse,
    PackageScheduleUpdate,
)
from app.services.client_package import (
    ClientPackageError,
    ClientPackageService,
    PackageLockedError,
)
from app.models.hr_user import HRUser
from app.services.hr_membership import (
    OPS_ROLES,
    find_ops_role_for_email,
    hr_display_name,
    upsert_hr_membership,
)
from app.services.storage import (
    LogoStorageError,
    LogoValidationError,
    upload_logo,
    validate_logo_upload,
)
from app.services.supabase_admin import SupabaseAdminError, invite_hr_user_by_email

router = APIRouter()
logger = logging.getLogger(__name__)


@router.post("/companies", response_model=CompanyCreateResponse)
async def create_company(
    body: CompanyCreateRequest,
    db: AsyncSession = Depends(get_db),
    _: HRUserContext = Depends(get_current_ops_user),
):
    """Insert a corporates row. Slug is generated from name when omitted.

    Args:
        body: Company name and optional slug.
        db: Async database session.
        _: Authenticated ops user.

    Returns:
        Inserted company id, name, slug, and created_at.
    """
    try:
        return await ClientPackageService.create_company(db, body)
    except ClientPackageError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.patch("/companies/{company_id}", response_model=CompanyCreateResponse)
async def update_company(
    company_id: UUID,
    body: CompanyUpdateRequest,
    db: AsyncSession = Depends(get_db),
    _: HRUserContext = Depends(get_current_ops_user),
):
    """Edit a company's display name or HR contact email.

    Ops writes go through the service role because ``corporates_update_own``
    RLS only lets HR users update their own tenant.

    Args:
        company_id: Target corporate UUID.
        body: Fields to change; omitted fields are left untouched.
        db: Async database session.
        _: Authenticated ops user.

    Returns:
        The updated company.
    """
    try:
        return await ClientPackageService.update_company(db, company_id, body)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ClientPackageError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.delete("/companies/{company_id}", response_model=CompanyCreateResponse)
async def delete_company(
    company_id: UUID,
    db: AsyncSession = Depends(get_db),
    _: HRUserContext = Depends(get_current_ops_user),
):
    """Soft-delete a company: hide it from active views, keep its records.

    Args:
        company_id: Target corporate UUID.
        db: Async database session.
        _: Authenticated ops user.

    Returns:
        The company with ``is_active`` set to False.
    """
    try:
        return await ClientPackageService.soft_delete_company(db, company_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/companies/{company_id}/logo", response_model=CompanyLogoResponse)
async def upload_company_logo(
    company_id: UUID,
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    _: HRUserContext = Depends(get_current_ops_user),
):
    """Upload a logo for any company to Supabase Storage and persist ``corporates.logo_url``.

    Args:
        company_id: Target corporate UUID.
        file: PNG, JPEG, or WebP image up to 2 MB.
        db: Async database session.
        _: Authenticated ops user.

    Returns:
        The persisted public logo URL.
    """
    exists = (
        await db.execute(
            select(Corporate.id).where(
                Corporate.id == company_id, Corporate.is_active.is_(True)
            )
        )
    ).scalar_one_or_none()
    if exists is None:
        raise HTTPException(status_code=404, detail="Company not found")

    raw = await file.read()
    try:
        filename, content_type = validate_logo_upload(
            file.content_type, raw, file.filename, corporate_id=company_id
        )
    except LogoValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    try:
        public_url = await run_in_threadpool(
            upload_logo, company_id, filename, raw, content_type
        )
    except LogoStorageError as exc:
        logger.error("Logo upload failed: %s", exc, exc_info=True)
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc

    try:
        company = await ClientPackageService.set_company_logo(db, company_id, public_url)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return CompanyLogoResponse(logo_url=company.logo_url or public_url)


@router.post(
    "/companies/{company_id}/invite-hr",
    response_model=HrInviteResponse,
)
async def invite_hr(
    company_id: UUID,
    body: HrInviteRequest,
    db: AsyncSession = Depends(get_db),
    _: HRUserContext = Depends(get_current_ops_user),
):
    """Invite an HR user via Supabase Auth Admin and map them to the company.

    Uses the service role key to call ``invite_user_by_email``, then upserts
    ``public.hr_users`` with ``role='hr'`` and stamps ``corporates.contact_email``.
    Emails already mapped to an ops role (admin/owner) are rejected with 409 so
    an invite can never demote an internal operator.

    Args:
        company_id: Target corporate UUID.
        body: Work email to invite.
        db: Async database session.
        _: Authenticated ops user.

    Returns:
        Success acknowledgement with the invited email.
    """
    corporate = (
        await db.execute(
            select(Corporate).where(
                Corporate.id == company_id, Corporate.is_active.is_(True)
            )
        )
    ).scalar_one_or_none()
    if not corporate:
        raise HTTPException(status_code=404, detail="Company not found")

    if await find_ops_role_for_email(db, body.email):
        raise HTTPException(
            status_code=409,
            detail="This email belongs to an internal operator and cannot be invited as HR.",
        )

    from app.services.email import resolve_frontend_origin

    redirect_to = f"{resolve_frontend_origin()}/client/dashboard"
    try:
        user_id = invite_hr_user_by_email(body.email, redirect_to=redirect_to)
    except SupabaseAdminError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    # One HR user maps to exactly one company. Re-inviting an email that is
    # already bound elsewhere must not silently move them (the old upsert
    # overwrote corporate_id, so HR landed in the wrong portal).
    existing = (
        await db.execute(select(HRUser).where(HRUser.user_id == user_id))
    ).scalar_one_or_none()
    if (
        existing is not None
        and existing.corporate_id != company_id
        and existing.role not in OPS_ROLES
    ):
        raise HTTPException(
            status_code=409,
            detail=(
                "This email already has HR access to another company. "
                "Remove them there before inviting them here."
            ),
        )

    await upsert_hr_membership(
        db,
        user_id=user_id,
        corporate_id=company_id,
        full_name=hr_display_name(body.email),
    )
    if not corporate.contact_email:
        corporate.contact_email = body.email
    # Persist a fully normalized whitelist so OTP lookup is case-stable.
    normalized = [
        entry.strip().lower()
        for entry in (corporate.allowed_hr_emails or [])
        if entry and str(entry).strip()
    ]
    if body.email not in normalized:
        normalized.append(body.email)
    corporate.allowed_hr_emails = normalized
    await db.commit()

    return HrInviteResponse(
        success=True,
        message="Access link sent",
        email=body.email,
    )


_CANDIDATE_OVERVIEW_COLUMNS = """
    id, corporate_id, package_id, full_name, email, access_code,
    logged_in_at, created_at, package_title, total_assessments,
    completed_assessments, technical_score, avg_score, evaluated,
    completed_at
"""

_CANDIDATE_OVERVIEW_SQL = f"""
    select {_CANDIDATE_OVERVIEW_COLUMNS}
      from public.candidate_overview
     where (cast(:package_id as uuid) is null or package_id = cast(:package_id as uuid))
     order by created_at desc
"""

_SCORECARD_CANDIDATE_SQL = f"""
    select {_CANDIDATE_OVERVIEW_COLUMNS}
      from public.candidate_overview
     where id = cast(:candidate_id as uuid)
"""

_SCORECARD_EVALUATION_SQL = """
    select payload, status, generated_at
      from public.candidate_evaluations
     where candidate_id = cast(:candidate_id as uuid)
     order by generated_at desc nulls last
     limit 1
"""

_SCORECARD_ASSESSMENTS_SQL = """
    select id, title, position, questions
      from public.assessments
     where package_id = cast(:package_id as uuid)
     order by position
"""

_SCORECARD_RESPONSES_SQL = """
    select assessment_id, question_id, response
      from public.candidate_responses
     where candidate_id = cast(:candidate_id as uuid)
"""

_SCORECARD_PROGRESS_SQL = """
    select assessment_id, status, score, completed_at
      from public.candidate_progress
     where candidate_id = cast(:candidate_id as uuid)
"""


@router.get("/candidates", response_model=list[AdminCandidateOverviewRow])
async def list_admin_candidates(
    package_id: UUID | None = Query(None),
    db: AsyncSession = Depends(get_db),
    _: HRUserContext = Depends(get_current_ops_user),
):
    """List ``candidate_overview`` rows across tenants for Assessment History.

    The ops console has no PostgREST grant on ``candidate_progress`` (the
    view is ``security_invoker``), so this read runs server-side behind the
    ops JWT instead of loosening RLS.

    Args:
        package_id: Optional package filter.
        db: Async database session.
        _: Authenticated ops user.

    Returns:
        Overview rows, newest first.
    """
    try:
        result = await db.execute(
            text(_CANDIDATE_OVERVIEW_SQL),
            {"package_id": str(package_id) if package_id else None},
        )
    except ProgrammingError as exc:
        raise HTTPException(status_code=503, detail=schema_drift_detail(exc)) from exc
    return [dict(row) for row in result.mappings().all()]


@router.get("/candidates/{candidate_id}/scorecard", response_model=AdminCandidateScorecard)
async def get_admin_candidate_scorecard(
    candidate_id: UUID,
    db: AsyncSession = Depends(get_db),
    _: HRUserContext = Depends(get_current_ops_user),
):
    """Return one candidate's overview, evaluation, questions, answers and progress.

    Same server-side read pattern as :func:`list_admin_candidates`: the ops
    console cannot read ``candidate_progress`` / ``candidate_responses``
    through PostgREST, so these reads run behind the ops JWT.

    Args:
        candidate_id: Target candidate UUID.
        db: Async database session.
        _: Authenticated ops user.

    Returns:
        Candidate overview row plus evaluation, assessments, responses, progress.
    """
    params = {"candidate_id": str(candidate_id)}
    try:
        candidate = (
            await db.execute(text(_SCORECARD_CANDIDATE_SQL), params)
        ).mappings().first()
        if candidate is None:
            raise HTTPException(status_code=404, detail="Candidate not found")

        evaluation = (
            await db.execute(text(_SCORECARD_EVALUATION_SQL), params)
        ).mappings().first()
        assessments = (
            await db.execute(
                text(_SCORECARD_ASSESSMENTS_SQL),
                {"package_id": str(candidate["package_id"])},
            )
        ).mappings().all()
        responses = (
            await db.execute(text(_SCORECARD_RESPONSES_SQL), params)
        ).mappings().all()
        progress = (
            await db.execute(text(_SCORECARD_PROGRESS_SQL), params)
        ).mappings().all()
    except ProgrammingError as exc:
        raise HTTPException(status_code=503, detail=schema_drift_detail(exc)) from exc

    return {
        "candidate": dict(candidate),
        "evaluation": dict(evaluation) if evaluation is not None else None,
        "assessments": [dict(row) for row in assessments],
        "responses": [dict(row) for row in responses],
        "progress": [dict(row) for row in progress],
    }


_PACKAGE_OVERVIEW_SQL = """
    select * from public.package_overview order by created_at desc
"""


@router.get("/packages", response_model=list[AdminPackageOverviewRow])
async def list_admin_packages(
    db: AsyncSession = Depends(get_db),
    _: HRUserContext = Depends(get_current_ops_user),
):
    """List ``package_overview`` rows across tenants (newest first).

    Same server-side pattern as :func:`list_admin_candidates`; replaces the
    console's direct PostgREST read of the view.

    Args:
        db: Async database session.
        _: Authenticated ops user.

    Returns:
        Package rows with corporate name/slug and candidate count.
    """
    try:
        result = await db.execute(text(_PACKAGE_OVERVIEW_SQL))
    except ProgrammingError as exc:
        raise HTTPException(status_code=503, detail=schema_drift_detail(exc)) from exc
    return [dict(row) for row in result.mappings().all()]


async def _load_corporate(db: AsyncSession, corporate_id: UUID) -> Corporate:
    corporate = (
        await db.execute(select(Corporate).where(Corporate.id == corporate_id))
    ).scalar_one_or_none()
    if corporate is None:
        raise HTTPException(status_code=404, detail="Company not found")
    return corporate


@router.get("/corporates/{corporate_id}", response_model=AdminCorporateRow)
async def get_admin_corporate(
    corporate_id: UUID,
    db: AsyncSession = Depends(get_db),
    _: HRUserContext = Depends(get_current_ops_user),
):
    """Return one ``corporates`` row for the branding page.

    Args:
        corporate_id: Target corporate UUID.
        db: Async database session.
        _: Authenticated ops user.

    Returns:
        The full corporate row.
    """
    return await _load_corporate(db, corporate_id)


@router.patch("/corporates/{corporate_id}", response_model=AdminCorporateRow)
async def update_admin_corporate(
    corporate_id: UUID,
    body: AdminCorporateBrandingUpdate,
    db: AsyncSession = Depends(get_db),
    _: HRUserContext = Depends(get_current_ops_user),
):
    """Update branding/contact fields on a corporate.

    Only fields present in the request body change; ``null`` or blank clears.

    Args:
        corporate_id: Target corporate UUID.
        body: Logo URL, brand color, contact email/phone.
        db: Async database session.
        _: Authenticated ops user.

    Returns:
        The updated corporate row.
    """
    corporate = await _load_corporate(db, corporate_id)
    for field in body.model_fields_set:
        setattr(corporate, field, getattr(body, field))
    await db.commit()
    await db.refresh(corporate)
    return corporate


@router.get("/packages/{package_id}", response_model=AdminPackageDetail)
async def get_admin_package(
    package_id: UUID,
    db: AsyncSession = Depends(get_db),
    _: HRUserContext = Depends(get_current_ops_user),
):
    """Return one package with module associations and custom questions.

    Args:
        package_id: Client package UUID.
        db: Async database session.
        _: Authenticated ops user.

    Returns:
        Package metadata, package_modules, and custom_technical_questions.
    """
    try:
        return await ClientPackageService.get_admin_package(db, package_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.delete("/packages/{package_id}", response_model=PackageDeleteResponse)
async def delete_admin_package(
    package_id: UUID,
    db: AsyncSession = Depends(get_db),
    _: HRUserContext = Depends(get_current_ops_user),
):
    """Soft-archive a published suite or hard-delete an unpublished draft.

    Published packages set ``is_active=False`` so candidate records remain.
    Drafts are removed entirely. Archived packages leave the company package grid.

    Args:
        package_id: Client package UUID.
        db: Async database session.
        _: Authenticated ops user.

    Returns:
        ``archived`` or ``deleted`` outcome with the package id.
    """
    try:
        return await ClientPackageService.soft_delete_package(db, package_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.put("/packages/{package_id}", response_model=AdminPackageDetail)
async def update_admin_package(
    package_id: UUID,
    body: AdminPackageUpdateRequest,
    db: AsyncSession = Depends(get_db),
    _: HRUserContext = Depends(get_current_ops_user),
):
    """Replace draft package metadata, modules, and custom questions.

    Published packages return HTTP 409 and are not mutated.

    Args:
        package_id: Client package UUID.
        body: Title, optional role/threshold/company, module ids, questions.
        db: Async database session.
        _: Authenticated ops user.

    Returns:
        Updated package detail after the transactional sync.
    """
    try:
        return await ClientPackageService.update_admin_package(db, package_id, body)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except PackageLockedError as exc:
        raise HTTPException(
            status_code=409,
            detail="Package is published and locked",
        ) from exc
    except ClientPackageError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except ProgrammingError as exc:
        raise HTTPException(status_code=503, detail=schema_drift_detail(exc)) from exc


@router.patch("/packages/{package_id}/schedule", response_model=PackageScheduleResponse)
async def update_package_schedule(
    package_id: UUID,
    body: PackageScheduleUpdate,
    db: AsyncSession = Depends(get_db),
    _: HRUserContext = Depends(get_current_ops_user),
):
    """Extend (or clear) a package deadline; works on published packages.

    Args:
        package_id: Client package UUID.
        body: New timezone-aware ``close_time`` or null for no deadline.
        db: Async database session.
        _: Authenticated ops user.

    Returns:
        The package's open/close window after the update.
    """
    try:
        return await ClientPackageService.update_schedule(db, package_id, body)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ClientPackageError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except ProgrammingError as exc:
        raise HTTPException(status_code=503, detail=schema_drift_detail(exc)) from exc

