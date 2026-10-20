"""HR candidate invitation: persist a pending candidate and queue SES mail."""
import logging

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import HRUserContext, get_current_hr_user, is_ops_role
from app.database import get_db
from app.models.corporate import Corporate
from app.models.package import Package
from app.schemas.candidate import CandidateInviteRequest, CandidateInviteResponse
from app.services.candidate_service import CandidateService
from app.services.email import (
    _assessment_invite_link,
    clean_recipient_email,
    resolve_frontend_origin,
)
from app.services.email_service import EmailService
from app.security import enforce_user_rate_limit, invite_limiter

logger = logging.getLogger("app.invites")

router = APIRouter()


async def _dispatch_candidate_invite(
    *,
    candidate_email: str,
    candidate_name: str,
    access_code: str,
    package_title: str,
    corporate_name: str | None,
    origin: str,
) -> None:
    """BackgroundTasks worker for one candidate invite; never raises silently.

    Args:
        candidate_email: Raw candidate address (sanitized before dispatch).
        candidate_name: Candidate display name for the email body.
        access_code: Candidate/package access code.
        package_title: Assessment package title.
        corporate_name: Hiring company shown in the email, if known.
        origin: Absolute frontend origin for the assessment link.
    """
    clean_email = clean_recipient_email(candidate_email)
    link = _assessment_invite_link(access_code, origin=origin)
    logger.info(
        "[INVITE QUEUED] Candidate=%s Code=%s Link=%s",
        clean_email or candidate_email,
        access_code,
        link,
    )
    try:
        sent = await EmailService.send_candidate_invite_email(
            clean_email or candidate_email,
            candidate_name,
            access_code,
            package_title,
            corporate_name,
            origin=origin,
        )
    except Exception:  # noqa: BLE001 - background task: log, never propagate
        logger.exception(
            "[INVITE FAILED] Candidate=%s Code=%s Link=%s",
            clean_email or candidate_email,
            access_code,
            link,
        )
        return
    if not sent:
        logger.error(
            "[INVITE FAILED] Candidate=%s Code=%s Link=%s "
            "(SES returned no MessageId; see app.email logs)",
            clean_email or candidate_email,
            access_code,
            link,
        )


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
    clean_email = clean_recipient_email(candidate.email)
    link = _assessment_invite_link(candidate.access_code, origin=origin)
    # Logged synchronously (before the 202 returns) so testers always have a
    # usable link/code even if SES sandbox drops the background delivery.
    logger.info(
        "[INVITE DISPATCHED] Candidate=%s Code=%s Link=%s",
        clean_email or candidate.email,
        candidate.access_code,
        link,
    )
    background_tasks.add_task(
        _dispatch_candidate_invite,
        candidate_email=candidate.email,
        candidate_name=candidate.full_name,
        access_code=candidate.access_code,
        package_title=package.title if package else "your assessment",
        corporate_name=corporate.name if corporate else None,
        origin=origin,
    )

    return CandidateInviteResponse(
        id=candidate.id,
        candidate_email=candidate.email,
        package_id=candidate.package_id,
        access_code=candidate.access_code,
        status="pending",
    )
