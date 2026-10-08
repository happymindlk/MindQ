"""Ops admin company + single-package endpoints."""
from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy import select
from sqlalchemy.exc import ProgrammingError
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import HRUserContext, get_current_ops_user
from app.config import settings
from app.database import get_db
from app.exceptions import schema_drift_detail
from app.models.corporate import Corporate
from app.schemas.client_package import (
    AdminPackageDetail,
    AdminPackageUpdateRequest,
    CompanyCreateRequest,
    CompanyCreateResponse,
    CompanyLogoResponse,
    CompanyUpdateRequest,
    HrInviteRequest,
    HrInviteResponse,
)
from app.services.client_package import (
    ClientPackageError,
    ClientPackageService,
    PackageLockedError,
)
from app.services.hr_membership import (
    find_ops_role_for_email,
    hr_display_name,
    upsert_hr_membership,
)
from app.services.storage import LogoValidationError, upload_logo, validate_logo_upload
from app.services.supabase_admin import SupabaseAdminError, invite_hr_user_by_email

router = APIRouter()


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


@router.post("/companies/{company_id}/logo", response_model=CompanyLogoResponse)
async def upload_company_logo(
    company_id: UUID,
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    _: HRUserContext = Depends(get_current_ops_user),
):
    """Upload a logo for any company to R2 and persist ``corporates.logo_url``.

    Args:
        company_id: Target corporate UUID.
        file: PNG, JPEG, WebP, or SVG image up to 2 MB.
        db: Async database session.
        _: Authenticated ops user.

    Returns:
        The persisted public logo URL.
    """
    exists = (
        await db.execute(select(Corporate.id).where(Corporate.id == company_id))
    ).scalar_one_or_none()
    if exists is None:
        raise HTTPException(status_code=404, detail="Company not found")

    if not settings.r2_configured or not settings.r2_public_base:
        raise HTTPException(status_code=503, detail="Logo storage is not configured")

    raw = await file.read()
    try:
        filename, content_type = validate_logo_upload(file.content_type, raw, file.filename)
    except LogoValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    public_url = upload_logo(company_id, filename, raw, content_type)
    if not public_url:
        raise HTTPException(status_code=502, detail="Failed to upload logo to object storage")

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
        await db.execute(select(Corporate).where(Corporate.id == company_id))
    ).scalar_one_or_none()
    if not corporate:
        raise HTTPException(status_code=404, detail="Company not found")

    if await find_ops_role_for_email(db, body.email):
        raise HTTPException(
            status_code=409,
            detail="This email belongs to an internal operator and cannot be invited as HR.",
        )

    redirect_to = f"{settings.FRONTEND_URL.rstrip('/')}/client/dashboard"
    try:
        user_id = invite_hr_user_by_email(body.email, redirect_to=redirect_to)
    except SupabaseAdminError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    await upsert_hr_membership(
        db,
        user_id=user_id,
        corporate_id=company_id,
        full_name=hr_display_name(body.email),
    )
    corporate.contact_email = body.email
    await db.commit()

    return HrInviteResponse(
        success=True,
        message="Access link sent",
        email=body.email,
    )


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


@router.put("/packages/{package_id}", response_model=AdminPackageDetail)
async def update_admin_package(
    package_id: UUID,
    body: AdminPackageUpdateRequest,
    db: AsyncSession = Depends(get_db),
    _: HRUserContext = Depends(get_current_ops_user),
):
    """Replace draft package metadata, modules, and custom questions.

    Published packages return HTTP 400 and are not mutated.

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
            status_code=400,
            detail="Published packages are locked and cannot be modified.",
        ) from exc
    except ClientPackageError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except ProgrammingError as exc:
        raise HTTPException(status_code=503, detail=schema_drift_detail(exc)) from exc
