"""Corporate branding endpoints (logo upload via Supabase Storage)."""
from __future__ import annotations

import logging
from uuid import UUID

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import HRUserContext, get_current_hr_user
from app.database import get_db
from app.services.client_package import ClientPackageService
from app.services.storage import (
    LogoStorageError,
    LogoValidationError,
    upload_logo,
    validate_logo_upload,
)

router = APIRouter()
logger = logging.getLogger(__name__)


@router.post("/{corporate_id}/logo")
async def upload_corporate_logo(
    corporate_id: UUID,
    file: UploadFile = File(...),
    hr: HRUserContext = Depends(get_current_hr_user),
    db: AsyncSession = Depends(get_db),
):
    """Upload a corporate logo to Supabase Storage and persist ``corporates.logo_url``.

    Tenant-scoped: the path ``corporate_id`` must match the caller's
    ``app_metadata.corporate_id``. Object keys are versioned
    (``{corporate_id}_{timestamp}.{ext}``) so CDN/browser caches do not
    serve a stale logo after replace.
    """
    if corporate_id != hr.corporate_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Forbidden")

    raw = await file.read()
    try:
        filename, content_type = validate_logo_upload(
            file.content_type, raw, file.filename, corporate_id=corporate_id
        )
    except LogoValidationError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    try:
        public_url = upload_logo(corporate_id, filename, raw, content_type)
    except LogoStorageError as exc:
        logger.error("Logo upload failed: %s", exc, exc_info=True)
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc

    try:
        company = await ClientPackageService.set_company_logo(db, corporate_id, public_url)
    except LookupError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

    logo_url = company.logo_url or public_url
    return {"logo_url": logo_url, "url": logo_url}
