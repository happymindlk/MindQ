"""Corporate branding endpoints (logo upload via Supabase Storage)."""
from __future__ import annotations

import logging
from uuid import UUID

from starlette.concurrency import run_in_threadpool
from fastapi import APIRouter, Depends, File, Header, HTTPException, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import HRUserContext, get_current_hr_user
from app.database import get_db
from app.services.client_package import ClientPackageService
from app.services.storage import (
    LOGO_MAX_BYTES,
    LogoStorageError,
    LogoValidationError,
    upload_logo,
    validate_logo_upload,
)
from app.services.upload_limits import (
    UploadTooLargeError,
    check_content_length,
    read_upload_capped,
)

router = APIRouter()
logger = logging.getLogger(__name__)


@router.post("/{corporate_id}/logo")
async def upload_corporate_logo(
    corporate_id: UUID,
    file: UploadFile = File(...),
    content_length: str | None = Header(None),
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

    try:
        # P2-09: bounded chunked read instead of loading the whole upload.
        check_content_length(content_length, LOGO_MAX_BYTES)
        raw = await read_upload_capped(file, LOGO_MAX_BYTES)
    except UploadTooLargeError as exc:
        raise HTTPException(
            status_code=413,
            detail="Logo must be 2 MB or smaller",
        ) from exc
    try:
        filename, content_type = validate_logo_upload(
            file.content_type, raw, file.filename, corporate_id=corporate_id
        )
    except LogoValidationError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    try:
        public_url = await run_in_threadpool(
            upload_logo, corporate_id, filename, raw, content_type
        )
    except LogoStorageError as exc:
        logger.error("Logo upload failed: %s", exc, exc_info=True)
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc

    try:
        company = await ClientPackageService.set_company_logo(db, corporate_id, public_url)
    except LookupError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

    logo_url = company.logo_url or public_url
    return {"logo_url": logo_url, "url": logo_url}
