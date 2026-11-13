"""Server-side finalizer for timed assessments past their deadline.

When a candidate starts a timed module and then closes the browser, the
attempt stays ``IN_PROGRESS`` until something submits it. This module
sweeps those rows, runs the same ``submit_test`` → scoring queue path as a
normal submit (using already-persisted ``candidate_responses``), and is
safe to call from every web worker via row locks + status transitions.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import defer

from app.database import SessionLocal
from app.exceptions import AssessmentAlreadySubmittedError
from app.jobs.enqueue import enqueue_finalize_and_score_ai
from app.models.assessment import Assessment
from app.models.candidate import Candidate
from app.models.candidate_progress import CandidateProgress
from app.services.candidate_service import (
    IN_PROGRESS_STATUS,
    CandidateService,
    is_strict_expired,
)

logger = logging.getLogger("app.assessment_expiry")

# Periodic sweep interval for the in-process background loop.
EXPIRY_SWEEP_INTERVAL_SECONDS = 45


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


async def list_expired_in_progress(
    session: AsyncSession,
    *,
    now: datetime | None = None,
) -> list[tuple[CandidateProgress, Assessment]]:
    """Return ``IN_PROGRESS`` attempts whose server deadline has passed.

    Args:
        session: Async database session.
        now: Clock override for tests; defaults to UTC now.

    Returns:
        Pairs of ``(progress, assessment)`` that should be auto-submitted.
    """
    clock = now or _utcnow()
    rows = (
        await session.execute(
            select(CandidateProgress, Assessment)
            .join(Assessment, Assessment.id == CandidateProgress.assessment_id)
            .where(
                CandidateProgress.status == IN_PROGRESS_STATUS,
                CandidateProgress.started_at.is_not(None),
            )
            .options(defer(Assessment.questions))
        )
    ).all()
    expired: list[tuple[CandidateProgress, Assessment]] = []
    for progress, assessment in rows:
        if is_strict_expired(assessment, progress, clock):
            expired.append((progress, assessment))
    return expired


async def finalize_one_expired(
    session: AsyncSession,
    *,
    candidate: Candidate,
    assessment_id: UUID,
) -> bool:
    """Finalize one expired attempt via the normal submit path.

    Args:
        session: Async database session.
        candidate: Candidate who owns the attempt.
        assessment_id: Timed module that has passed its deadline.

    Returns:
        ``True`` when this call transitioned the row to ``COMPLETED``;
        ``False`` when another worker already finalized it.
    """
    try:
        await CandidateService.submit_test(
            session,
            candidate,
            assessment_id,
            pending_responses=None,
            client_duration_seconds=None,
        )
    except AssessmentAlreadySubmittedError:
        return False
    return True


async def finalize_expired_assessments(
    session: AsyncSession,
    *,
    now: datetime | None = None,
    enqueue: bool = True,
) -> list[tuple[UUID, UUID]]:
    """Idempotently complete every expired ``IN_PROGRESS`` timed attempt.

    Uses the same scoring / Gemini / PDF pipeline as a normal candidate
    submit (``enqueue_finalize_and_score_ai``). Concurrent sweeps and a
    simultaneous candidate click are serialized by ``submit_test``'s
    ``FOR UPDATE`` lock and the ``IN_PROGRESS`` → ``COMPLETED`` transition.

    Args:
        session: Async database session (``submit_test`` commits per row).
        now: Clock override for tests.
        enqueue: When True, queue post-submit scoring for each new completion.

    Returns:
        ``(candidate_id, assessment_id)`` pairs newly marked completed.
    """
    expired = await list_expired_in_progress(session, now=now)
    if not expired:
        return []

    candidate_ids = {progress.candidate_id for progress, _ in expired}
    candidates = (
        await session.execute(
            select(Candidate).where(
                Candidate.id.in_(tuple(candidate_ids)),
                Candidate.deleted_at.is_(None),
            )
        )
    ).scalars().all()
    by_id = {c.id: c for c in candidates}

    finalized: list[tuple[UUID, UUID]] = []
    for progress, _assessment in expired:
        candidate = by_id.get(progress.candidate_id)
        if candidate is None:
            logger.warning(
                "expiry_skip_missing_candidate progress_id=%s candidate_id=%s",
                progress.id,
                progress.candidate_id,
            )
            continue
        claimed = await finalize_one_expired(
            session,
            candidate=candidate,
            assessment_id=progress.assessment_id,
        )
        if not claimed:
            continue
        pair = (candidate.id, progress.assessment_id)
        finalized.append(pair)
        if enqueue:
            await enqueue_finalize_and_score_ai(candidate.id, progress.assessment_id)
        logger.info(
            "assessment_auto_finalized candidate_id=%s assessment_id=%s",
            candidate.id,
            progress.assessment_id,
        )
    return finalized


async def ensure_expired_assessments_finalized() -> int:
    """Best-effort sweep in its own session (safe before dashboard reads).

    Returns:
        Number of assessments newly finalized, or 0 on failure.
    """
    try:
        async with SessionLocal() as session:
            finalized = await finalize_expired_assessments(session, enqueue=True)
        return len(finalized)
    except Exception:
        logger.exception(
            "finalize_expired_sweep_failed",
            extra={"event": "finalize_expired_sweep_failed"},
        )
        return 0


async def run_expiry_sweep_loop(
    *,
    interval_seconds: float = EXPIRY_SWEEP_INTERVAL_SECONDS,
    stop_event: asyncio.Event | None = None,
) -> None:
    """Background loop: finalize expired attempts every ``interval_seconds``.

    Args:
        interval_seconds: Sleep between sweeps (30–60s recommended).
        stop_event: Optional event that ends the loop when set.
    """
    stop = stop_event or asyncio.Event()
    logger.info(
        "expiry_sweep_loop_started interval_s=%s",
        interval_seconds,
        extra={"event": "expiry_sweep_loop_started"},
    )
    while not stop.is_set():
        await ensure_expired_assessments_finalized()
        try:
            await asyncio.wait_for(stop.wait(), timeout=interval_seconds)
        except asyncio.TimeoutError:
            continue
    logger.info("expiry_sweep_loop_stopped", extra={"event": "expiry_sweep_loop_stopped"})
