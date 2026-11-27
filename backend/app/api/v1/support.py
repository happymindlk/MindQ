"""Public Technical Support ticket submission + SES notify."""
from __future__ import annotations

import html
import logging
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, Request
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import candidate_id_from_authorization
from app.config import settings
from app.database import get_db
from app.models.candidate import Candidate
from app.models.package import Package
from app.models.support_ticket import SupportTicket
from app.schemas.support import SupportSubmitRequest, SupportSubmitResponse
from app.security import enforce_rate_limit, public_limiter
from app.services.email import send_transactional_email

logger = logging.getLogger("app.support")

router = APIRouter()


async def _resolve_candidate_link(
    db: AsyncSession,
    *,
    candidate_id: UUID | None,
    access_code: str | None,
    email: str,
) -> tuple[UUID | None, UUID | None]:
    """Resolve ``(candidate_id, corporate_id)`` for ticket linkage.

    Only proofs the submitter actually holds are trusted:

    1. ``candidate_id`` from a **verified candidate token** (never the body).
    2. An access code (+ email to pick the invited candidate).

    An email alone, or a raw UUID in the body, links nothing: anyone could
    otherwise file tickets into another tenant's queue.

    Args:
        db: Async database session.
        candidate_id: Candidate id taken from a verified bearer token, or None.
        access_code: Package or candidate access code from the form/URL.
        email: Submitter email, used only together with an access code.

    Returns:
        Pair of nullable UUIDs for ticket linkage.
    """
    email_norm = (email or "").strip().lower()
    code = (access_code or "").strip()

    if candidate_id:
        candidate = (
            await db.execute(
                select(Candidate).where(
                    Candidate.id == candidate_id,
                    Candidate.deleted_at.is_(None),
                )
            )
        ).scalars().first()
        if candidate:
            return candidate.id, candidate.corporate_id

    if code:
        package = (
            await db.execute(
                select(Package).where(
                    Package.access_code.in_((code, code.upper())),
                )
            )
        ).scalars().first()
        if package:
            if email_norm:
                invited = (
                    await db.execute(
                        select(Candidate).where(
                            Candidate.package_id == package.id,
                            func.lower(Candidate.email) == email_norm,
                            Candidate.deleted_at.is_(None),
                        )
                    )
                ).scalars().first()
                if invited:
                    return invited.id, invited.corporate_id
            return None, package.corporate_id

        by_candidate_code = (
            await db.execute(
                select(Candidate).where(
                    func.lower(Candidate.access_code) == code.lower(),
                    Candidate.deleted_at.is_(None),
                    *(
                        [func.lower(Candidate.email) == email_norm]
                        if email_norm
                        else []
                    ),
                )
            )
        ).scalars().first()
        if by_candidate_code:
            return by_candidate_code.id, by_candidate_code.corporate_id

    return None, None


def _support_email_html(ticket: SupportTicket) -> str:
    """Build a plain HTML body for the ops support inbox."""
    rows = [
        ("Ticket ID", str(ticket.id)),
        ("Status", ticket.status),
        ("Category", ticket.issue_category),
        ("Submitter email", ticket.submitter_email or ""),
        ("Contact number", ticket.contact_number or ""),
        ("Access code", ticket.access_code_entered or ""),
        ("Entered name", ticket.entered_name or ""),
        ("Candidate ID", str(ticket.candidate_id) if ticket.candidate_id else ""),
        ("Corporate ID", str(ticket.corporate_id) if ticket.corporate_id else ""),
        ("Device ID", ticket.device_id or ""),
        ("Browser", ticket.browser or ticket.user_agent or ""),
        ("Page URL", ticket.page_url or ticket.path or ""),
    ]
    lines = [
        "<h2>Technical Support ticket</h2>",
        "<table style='border-collapse:collapse;font-family:sans-serif;font-size:14px'>",
    ]
    for label, value in rows:
        lines.append(
            "<tr>"
            f"<td style='padding:4px 12px 4px 0;color:#555;vertical-align:top'>{html.escape(label)}</td>"
            f"<td style='padding:4px 0;vertical-align:top'>{html.escape(value)}</td>"
            "</tr>"
        )
    lines.append("</table>")
    lines.append("<h3>Description</h3>")
    lines.append(
        f"<pre style='white-space:pre-wrap;font-family:sans-serif'>{html.escape(ticket.description)}</pre>"
    )
    return "\n".join(lines)


def _send_support_notification(ticket_id: UUID, payload: dict) -> None:
    """Background SES send; log failures explicitly (never raise to the HTTP path)."""
    to_addr = (getattr(settings, "SUPPORT_EMAIL", None) or "").strip()
    if not to_addr:
        logger.error(
            "support_ticket_email_skipped_no_inbox ticket_id=%s",
            ticket_id,
        )
        return
    subject = (
        f"[MindQ Support] {payload.get('issue_category') or 'TECHNICAL'} — "
        f"{payload.get('submitter_email') or 'unknown'}"
    )
    try:
        result = send_transactional_email(
            to_addr,
            subject,
            payload["html"],
            reply_to=payload.get("reply_to"),
            raise_on_error=False,
        )
        if result is None:
            logger.error(
                "support_ticket_email_failed ticket_id=%s to=%s",
                ticket_id,
                to_addr,
            )
        else:
            logger.info(
                "support_ticket_email_sent ticket_id=%s MessageId=%s",
                ticket_id,
                result.get("MessageId") or result.get("id"),
            )
    except Exception:  # noqa: BLE001 — background task must not crash silently
        logger.exception(
            "support_ticket_email_exception ticket_id=%s to=%s",
            ticket_id,
            to_addr,
        )


@router.post("/submit", response_model=SupportSubmitResponse)
async def submit_support_ticket(
    body: SupportSubmitRequest,
    request: Request,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
):
    """Persist a candidate (or anonymous) technical-support report and email ops.

    Auth is optional. Candidate/corporate are linked from a verified candidate
    bearer token, or from ``access_code`` / ``package_code`` (+ email). A
    ``candidate_id`` in the body is ignored (kept in the schema so older
    clients do not get a 422).
    """
    enforce_rate_limit(public_limiter, request, "support_submit")
    token_candidate_id = candidate_id_from_authorization(
        request.headers.get("authorization")
    )

    access_code = (body.access_code or body.package_code or "").strip() or None
    description = (body.description or body.details or "").strip()
    if access_code:
        # Keep package code discoverable in free-text for older triage views.
        details = f"[Package: {access_code}] {description}"
    else:
        details = description

    candidate_id, corporate_id = await _resolve_candidate_link(
        db,
        candidate_id=token_candidate_id,
        access_code=access_code,
        email=str(body.email),
    )

    ticket = SupportTicket(
        corporate_id=corporate_id,
        candidate_id=candidate_id,
        submitter_email=str(body.email).strip().lower(),
        contact_number=body.contact_number.strip(),
        access_code_entered=access_code,
        entered_name=(body.entered_name or "").strip() or None,
        issue_category=(body.issue_category or "TECHNICAL").strip() or "TECHNICAL",
        details=details,
        description=description,
        device_id=body.device_id,
        browser=body.browser or body.user_agent,
        page_url=body.page_url,
        path=body.path,
        user_agent=body.user_agent or body.browser,
        status="OPEN",
    )
    db.add(ticket)
    await db.commit()
    await db.refresh(ticket)

    background_tasks.add_task(
        _send_support_notification,
        ticket.id,
        {
            "html": _support_email_html(ticket),
            "reply_to": ticket.submitter_email,
            "submitter_email": ticket.submitter_email,
            "issue_category": ticket.issue_category,
        },
    )

    logger.info(
        "support_ticket_created",
        extra={
            "event": "support_ticket_created",
            "request_id": getattr(request.state, "request_id", None),
            "ticket_id": str(ticket.id),
            "has_candidate": candidate_id is not None,
            "has_corporate": corporate_id is not None,
        },
    )
    return SupportSubmitResponse(id=ticket.id, created_at=ticket.created_at)
