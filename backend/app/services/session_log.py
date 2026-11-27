"""Persist candidate session audit events (login / module timing)."""
from __future__ import annotations

import hashlib
import logging
from datetime import datetime
from typing import Any
from uuid import UUID

from fastapi import Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.candidate_session_log import CandidateSessionLog
from app.security import client_ip

logger = logging.getLogger("app.session_log")

LOGIN = "LOGIN"
MODULE_START = "MODULE_START"
MODULE_COMPLETE = "MODULE_COMPLETE"
MODULE_TIMEOUT = "MODULE_TIMEOUT"


def hash_client_ip(request: Request | None) -> str | None:
    """SHA-256 hex digest of the resolved client IP (never store raw IP).

    Args:
        request: Incoming FastAPI request, if available.

    Returns:
        Hex digest string, or None when no request/IP is available.
    """
    if request is None:
        return None
    raw = (client_ip(request) or "").strip()
    if not raw:
        return None
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def device_headers(request: Request | None) -> tuple[str | None, str | None]:
    """Read ``X-Device-Id`` / ``X-Browser-Info`` from the request.

    Args:
        request: Incoming FastAPI request, if available.

    Returns:
        ``(device_id, browser)`` pair (each may be None).
    """
    if request is None:
        return None, None
    device_id = (request.headers.get("X-Device-Id") or "").strip() or None
    browser = (request.headers.get("X-Browser-Info") or "").strip() or None
    if browser and len(browser) > 1024:
        browser = browser[:1024]
    return device_id, browser


async def record_session_event(
    session: AsyncSession,
    *,
    corporate_id: UUID,
    candidate_id: UUID,
    event_type: str,
    assessment_id: UUID | None = None,
    assessment_name: str | None = None,
    duration_seconds: int | None = None,
    occurred_at: datetime | None = None,
    device_id: str | None = None,
    browser: str | None = None,
    ip_hash: str | None = None,
    request: Request | None = None,
    commit: bool = False,
) -> CandidateSessionLog:
    """Insert one ``candidate_session_logs`` row.

    Args:
        session: Open async SQLAlchemy session.
        corporate_id: Tenant id.
        candidate_id: Candidate id.
        event_type: One of LOGIN / MODULE_START / MODULE_COMPLETE / MODULE_TIMEOUT.
        assessment_id: Optional module id.
        assessment_name: Optional module title snapshot.
        duration_seconds: Optional elapsed seconds for complete/timeout.
        occurred_at: Event timestamp (defaults to DB/model now).
        device_id: Explicit device id; falls back to ``X-Device-Id``.
        browser: Explicit browser string; falls back to ``X-Browser-Info``.
        ip_hash: Explicit IP hash; falls back to hashing ``client_ip``.
        request: Optional request for header/IP fallbacks.
        commit: When True, commit immediately (otherwise caller owns the txn).

    Returns:
        The unsaved/saved ``CandidateSessionLog`` instance.
    """
    hdr_device, hdr_browser = device_headers(request)
    row = CandidateSessionLog(
        corporate_id=corporate_id,
        candidate_id=candidate_id,
        assessment_id=assessment_id,
        assessment_name=assessment_name,
        event_type=event_type,
        duration_seconds=duration_seconds,
        device_id=device_id or hdr_device,
        browser=browser or hdr_browser,
        ip_hash=ip_hash if ip_hash is not None else hash_client_ip(request),
    )
    if occurred_at is not None:
        row.occurred_at = occurred_at
    session.add(row)
    if commit:
        await session.commit()
        await session.refresh(row)
    logger.info(
        "candidate_session_log",
        extra={
            "event": "candidate_session_log",
            "event_type": event_type,
            "candidate_id": str(candidate_id),
            "assessment_id": str(assessment_id) if assessment_id else None,
            "duration_seconds": duration_seconds,
        },
    )
    return row


#: Upper bound for one session-log page (P1-17).
SESSION_LOG_MAX_LIMIT = 2000


async def list_session_logs_for_candidate(
    session: AsyncSession,
    candidate_id: UUID,
    *,
    limit: int = 500,
    offset: int = 0,
) -> list[CandidateSessionLog]:
    """Return chronological session logs for one candidate (one page).

    Args:
        session: Async database session.
        candidate_id: Candidate whose audit trail to load.
        limit: Max rows (capped at ``SESSION_LOG_MAX_LIMIT``).
        offset: Rows to skip.

    Returns:
        Rows ordered by ``occurred_at`` ascending.
    """
    limit = max(1, min(int(limit), SESSION_LOG_MAX_LIMIT))
    result = await session.execute(
        select(CandidateSessionLog)
        .where(CandidateSessionLog.candidate_id == candidate_id)
        .order_by(CandidateSessionLog.occurred_at.asc(), CandidateSessionLog.id)
        .limit(limit)
        .offset(max(0, int(offset)))
    )
    return list(result.scalars().all())


def duration_from_progress(progress: Any) -> int | None:
    """Derive integer duration seconds from a progress row.

    Prefers ``server_duration_seconds``, else ``started_at`` → ``completed_at``.

    Args:
        progress: ``CandidateProgress``-like object.

    Returns:
        Non-negative integer seconds, or None when unknown.
    """
    server = getattr(progress, "server_duration_seconds", None)
    if server is not None:
        try:
            return max(0, int(round(float(server))))
        except (TypeError, ValueError):
            pass
    started = getattr(progress, "started_at", None)
    completed = getattr(progress, "completed_at", None)
    if started is not None and completed is not None:
        return max(0, int(round((completed - started).total_seconds())))
    return None
