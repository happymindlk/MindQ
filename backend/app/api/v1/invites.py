"""HR candidate invitation: persist a pending candidate and queue SES mail."""
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import HRUserContext, get_current_hr_user, is_ops_role
from app.database import get_db
from app.models.corporate import Corporate
from app.models.package import Package
from app.schemas.candidate import CandidateInviteRequest, CandidateInviteResponse
from app.services.candidate_service import CandidateService
from app.services.email import resolve_frontend_origin
from app.services.email_service import EmailService
from app.security import enforce_user_rate_limit, invite_limiter

router = APIRouter()


@router.post(
    "/invite",
    response_model=CandidateInviteResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def invite_candidate(
    body: CandidateInviteRequest,
    background_tasks: BackgroundTasks,
    request: Request,
    hr: HRUserContext = Depends(get_current_hr_user),
    db: AsyncSession = Depends(get_db),
):
    """Create a pending candidate and queue the invitation email via SES.

    Tenant is the package's corporate_id. HR may only invite within their
    own tenant; ops may invite for any company package. Returns 202 immediately
    so SES latency never blocks the response.
    """
    enforce_user_rate_limit(invite_limiter, hr.user_id, "candidate_invite")
    if not is_ops_role(hr.role) and body.corporate_id != hr.corporate_id:
        raise HTTPException(status_code=403, detail="corporate_id does not match session")

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

    origin = resolve_frontend_origin(request)
    background_tasks.add_task(
        EmailService.send_candidate_invite_email,
        candidate.email,
        candidate.full_name,
        candidate.access_code,
        package.title if package else "your assessment",
        corporate.name if corporate else None,
        origin=origin,
    )

    return CandidateInviteResponse(
        id=candidate.id,
        candidate_email=candidate.email,
        package_id=candidate.package_id,
        access_code=candidate.access_code,
        status="pending",
    )
