"""ARQ task entrypoints — thin wrappers over existing service helpers."""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Any
from uuid import UUID

from starlette.concurrency import run_in_threadpool

from app.services.background import finalize_and_score_ai, refresh_report_synthesis
from app.services.email import send_transactional_email
from app.services.email_service import EmailService
from app.services import storage as storage_service

logger = logging.getLogger(__name__)


def _as_uuid(value: UUID | str) -> UUID:
    """Coerce job payload ids that may arrive as strings after serialization."""
    return value if isinstance(value, UUID) else UUID(str(value))


async def task_finalize_and_score_ai(
    ctx: dict[str, Any],
    candidate_id: UUID | str,
    assessment_id: UUID | str,
) -> None:
    """Score a submitted module, then run Gemini / HR email / PDF prewarm.

    Args:
        ctx: ARQ worker context (unused; kept for the ARQ calling convention).
        candidate_id: Candidate who submitted.
        assessment_id: Assessment that was submitted.
    """
    del ctx
    await finalize_and_score_ai(_as_uuid(candidate_id), _as_uuid(assessment_id))


async def task_refresh_report_synthesis(
    ctx: dict[str, Any],
    candidate_id: UUID | str,
) -> None:
    """Backfill technical grades and regenerate the MindQ Report narrative.

    Args:
        ctx: ARQ worker context.
        candidate_id: Candidate whose report is being viewed.
    """
    del ctx
    await refresh_report_synthesis(_as_uuid(candidate_id))


async def task_dispatch_candidate_invite(
    ctx: dict[str, Any],
    *,
    candidate_email: str,
    candidate_name: str,
    access_code: str,
    package_title: str,
    corporate_name: str | None,
    origin: str,
    close_time: datetime | str | None = None,
    candidate_first_name: str | None = None,
) -> None:
    """Send one candidate invite via SES.

    Args:
        ctx: ARQ worker context.
        candidate_email: Recipient address.
        candidate_name: Display name for the email body.
        access_code: Candidate PIN.
        package_title: Assessment package title.
        corporate_name: Hiring company name, if known.
        origin: Absolute frontend origin for the assessment link.
        close_time: Package window end (UTC), if enforced.
        candidate_first_name: Greeting name override.
    """
    del ctx
    # Lazy import avoids circular import: invites → enqueue → tasks → invites.
    from app.api.v1.invites import _dispatch_candidate_invite

    parsed_close: datetime | None
    if close_time is None or isinstance(close_time, datetime):
        parsed_close = close_time
    else:
        parsed_close = datetime.fromisoformat(str(close_time))
    await _dispatch_candidate_invite(
        candidate_email=candidate_email,
        candidate_name=candidate_name,
        access_code=access_code,
        package_title=package_title,
        corporate_name=corporate_name,
        origin=origin,
        close_time=parsed_close,
        candidate_first_name=candidate_first_name,
    )


async def task_send_package_share(
    ctx: dict[str, Any],
    recipient: str,
    subject: str,
    html_content: str,
) -> None:
    """Send a package-share transactional email.

    Args:
        ctx: ARQ worker context.
        recipient: HR / ops recipient address.
        subject: Email subject.
        html_content: Rendered HTML body.
    """
    del ctx
    try:
        await run_in_threadpool(
            send_transactional_email, recipient, subject, html_content
        )
    except Exception:  # noqa: BLE001 — worker / inline path must not raise
        logger.exception(
            "package_share_email_failed recipient=%s subject=%s",
            recipient,
            subject,
        )


async def task_send_nudge_email(
    ctx: dict[str, Any],
    email: str,
    name: str,
    access_code: str,
    package_title: str,
) -> None:
    """Send a candidate reminder email.

    Args:
        ctx: ARQ worker context.
        email: Candidate email.
        name: Candidate display name.
        access_code: Candidate / package access code.
        package_title: Assessment package title.
    """
    del ctx
    await EmailService.send_nudge_email(email, name, access_code, package_title)


async def task_store_cached_report(
    ctx: dict[str, Any],
    corporate_id: UUID | str,
    candidate_id: UUID | str,
    cache_key: str,
    content: bytes,
) -> None:
    """Persist a rendered MindQ Report PDF in object storage.

    Args:
        ctx: ARQ worker context.
        corporate_id: Tenant id used as the object prefix.
        candidate_id: Candidate id used as the second path segment.
        cache_key: Content-addressed report cache key.
        content: PDF bytes.
    """
    del ctx
    await run_in_threadpool(
        storage_service.store_cached_report,
        _as_uuid(corporate_id),
        _as_uuid(candidate_id),
        cache_key,
        content,
    )


TASK_FUNCTIONS = (
    task_finalize_and_score_ai,
    task_refresh_report_synthesis,
    task_dispatch_candidate_invite,
    task_send_package_share,
    task_send_nudge_email,
    task_store_cached_report,
)
