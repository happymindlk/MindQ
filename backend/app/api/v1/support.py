from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
import logging

from app.database import get_db
from app.models.candidate import Candidate
from app.models.support_ticket import SupportTicket
from app.schemas.support import SupportSubmitRequest, SupportSubmitResponse
from app.security import enforce_rate_limit, public_limiter

logger = logging.getLogger("app.support")

router = APIRouter()


@router.post("/submit", response_model=SupportSubmitResponse)
async def submit_support_ticket(
    body: SupportSubmitRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Persist a candidate (or anonymous) technical-support report.

    Auth is optional: if candidate_id is provided and exists, we attach the
    corporate for HR visibility. Always returns 200 with a ticket id.
    """
    enforce_rate_limit(public_limiter, request, "support_submit")
    corporate_id = None
    candidate_id = body.candidate_id
    if candidate_id:
        candidate = (
            await db.execute(select(Candidate).where(Candidate.id == candidate_id))
        ).scalars().first()
        if candidate:
            corporate_id = candidate.corporate_id
        else:
            candidate_id = None

    ticket = SupportTicket(
        corporate_id=corporate_id,
        candidate_id=candidate_id,
        details=body.details.strip(),
        path=body.path,
        user_agent=body.user_agent,
    )
    db.add(ticket)
    await db.commit()
    await db.refresh(ticket)
    logger.info(
        "support_ticket_created",
        extra={
            "event": "support_ticket_created",
            "request_id": getattr(request.state, "request_id", None),
            "ticket_id": str(ticket.id),
            "has_candidate": candidate_id is not None,
        },
    )
    return SupportSubmitResponse(id=ticket.id, created_at=ticket.created_at)
