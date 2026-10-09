"""Corporate branding endpoints (logo upload via R2)."""
from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status

from app.auth import HRUserContext, get_current_hr_user
from app.config import settings
from app.services.storage import LogoValidationError, upload_logo, validate_logo_upload

router = APIRouter()


@router.post("/{corporate_id}/logo")
async def upload_corporate_logo(
    corporate_id: UUID,
    file: UploadFile = File(...),
    hr: HRUserContext = Depends(get_current_hr_user),
):
    """Upload a corporate logo to R2 and return its public URL.

    Tenant-scoped: the path ``corporate_id`` must match the caller's
    ``app_metadata.corporate_id``. The frontend persists the returned URL
    on the corporates row via Supabase RLS.
    """
    if corporate_id != hr.corporate_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Forbidden")

    if not settings.r2_configured or not settings.r2_public_base:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Logo storage is not configured",
        )

    raw = await file.read()
    try:
        filename, content_type = validate_logo_upload(file.content_type, raw, file.filename)
    except LogoValidationError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    public_url = upload_logo(corporate_id, filename, raw, content_type)
    if not public_url:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Failed to upload logo to object storage",
        )

    return {"logo_url": public_url, "url": public_url}
