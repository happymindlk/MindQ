"""HR candidate invitation: persist a pending candidate and dispatch Resend mail."""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import HRUserContext, get_current_hr_user, is_ops_role
from app.config import settings
from app.database import get_db
from app.models.corporate import Corporate
from app.models.package import Package
from app.schemas.candidate import CandidateInviteRequest, CandidateInviteResponse
from app.services.candidate_service import CandidateService
from app.services.email_service import EmailService

router = APIRouter()


@router.post("/invite", response_model=CandidateInviteResponse)
async def invite_candidate(
    body: CandidateInviteRequest,
    hr: HRUserContext = Depends(get_current_hr_user),
    db: AsyncSession = Depends(get_db),
):
    """Create a pending candidate and send the Resend invitation email.

    Tenant is the package's corporate_id. HR may only invite within their
    own tenant; ops may invite for any company package.
    """
    if not is_ops_role(hr.role) and body.corporate_id != hr.corporate_id:
        raise HTTPException(status_code=403, detail="corporate_id does not match session")

    if not settings.resend_configured:
        raise HTTPException(
            status_code=503,
            detail="Resend is not configured (RESEND_API_KEY missing)",
        )

    package = (
        await db.execute(select(Package).where(Package.id == body.package_id))
    ).scalars().first()
    if not package:
        raise HTTPException(status_code=404, detail="Package not found")
    if getattr(package, "status", None) == "draft":
        raise HTTPException(status_code=400, detail="Package is not published")
    if not is_ops_role(hr.role) and package.corporate_id != hr.corporate_id:
        raise HTTPException(status_code=403, detail="corporate_id does not match session")

    target_corporate_id = package.corporate_id

    try:
        candidate, _created = await CandidateService.invite(
            db,
            email=str(body.candidate_email),
            package_id=body.package_id,
            corporate_id=target_corporate_id,
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    corporate = (
        await db.execute(select(Corporate).where(Corporate.id == candidate.corporate_id))
    ).scalar_one_or_none()

    try:
        await EmailService.send_candidate_invite_email(
            candidate.email,
            candidate.full_name,
            candidate.access_code,
            package.title if package else "your assessment",
            corporate.name if corporate else None,
            raise_on_error=True,
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    return CandidateInviteResponse(
        id=candidate.id,
        candidate_email=candidate.email,
        package_id=candidate.package_id,
        access_code=candidate.access_code,
        status="pending",
    )
