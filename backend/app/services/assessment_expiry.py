"""Server-side finalizer for timed assessments past their deadline.

When a candidate starts a timed module and then closes the browser, the
attempt stays ``IN_PROGRESS`` until something submits it. This module
sweeps those rows, runs the same ``submit_test`` → scoring queue path as a
normal submit (using already-persisted ``candidate_responses``), and is
safe to call from every web worker via row locks + status transitions.
"""
from __future__ import annotations

import asyncio
import contextlib
import logging
from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import func, select
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
    is_display_expired,
    request_clock,
)
from app.services.session_log import MODULE_TIMEOUT, duration_from_progress, record_session_event

logger = logging.getLogger("app.assessment_expiry")

# Periodic sweep interval for the dev-only in-process loop (ARQ cron runs at :00/:30).
EXPIRY_SWEEP_INTERVAL_SECONDS = 45
# Rows finalized per sweep; the next cron tick picks up any remainder.
EXPIRY_SWEEP_BATCH_LIMIT = 100


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


async def list_expired_in_progress(
    session: AsyncSession,
    *,
    now: datetime | None = None,
    candidate_id: UUID | None = None,
) -> list[tuple[CandidateProgress, Assessment]]:
    """Return ``IN_PROGRESS`` attempts whose display deadline has passed.

    Args:
        session: Async database session.
        now: Clock override for tests; defaults to the database ``now()`` so
            app-node clock skew cannot move the deadline (P2-05).
        candidate_id: When set, only that candidate's attempts are considered.

    Returns:
        Pairs of ``(progress, assessment)`` that should be auto-submitted.
    """
    stmt = (
        select(CandidateProgress, Assessment, func.now().label("db_now"))
        .join(Assessment, Assessment.id == CandidateProgress.assessment_id)
        .where(
            CandidateProgress.status == IN_PROGRESS_STATUS,
            CandidateProgress.started_at.is_not(None),
        )
        .options(defer(Assessment.questions))
    )
    if candidate_id is not None:
        stmt = stmt.where(CandidateProgress.candidate_id == candidate_id)
    rows = (await session.execute(stmt)).all()
    expired: list[tuple[CandidateProgress, Assessment]] = []
    for progress, assessment, db_now in rows:
        clock = now or _aware(db_now) or _utcnow()
        if is_display_expired(assessment, progress, clock):
            expired.append((progress, assessment))
    return expired


def _aware(value: object) -> datetime | None:
    """Timezone-aware UTC copy of a DB timestamp; None for non-datetimes."""
    if not isinstance(value, datetime):
        return None
    return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)


async def finalize_one_expired(
    session: AsyncSession,
    *,
    candidate: Candidate,
    assessment_id: UUID,
    completed_at: datetime | None = None,
) -> bool:
    """Finalize one expired attempt via the normal submit path.

    ``submit_test`` takes ``FOR UPDATE`` and transitions ``IN_PROGRESS`` →
    ``COMPLETED``, so concurrent client/worker calls never double-submit.

    Args:
        session: Async database session.
        candidate: Candidate who owns the attempt.
        assessment_id: Timed module that has passed its deadline.
        completed_at: Optional stamp (defaults to now; pass ``expires_at`` for
            server auto-finalize audit fidelity).

    Returns:
        ``True`` when this call transitioned the row to ``COMPLETED``;
        ``False`` when another worker already finalized it.
    """
    try:
        progress, _package_complete, _company, assessment_name = (
            await CandidateService.submit_test(
                session,
                candidate,
                assessment_id,
                pending_responses=None,
                client_duration_seconds=None,
                completed_at=completed_at,
            )
        )
    except AssessmentAlreadySubmittedError:
        return False
    if progress is not None:
        await record_session_event(
            session,
            corporate_id=candidate.corporate_id,
            candidate_id=candidate.id,
            event_type=MODULE_TIMEOUT,
            assessment_id=assessment_id,
            assessment_name=assessment_name,
            duration_seconds=duration_from_progress(progress),
            occurred_at=progress.completed_at,
            commit=True,
        )
    return progress is not None


async def finalize_expired_assessment(
    session: AsyncSession,
    candidate_id: UUID,
    *,
    assessment_id: UUID | None = None,
    now: datetime | None = None,
    enqueue: bool = True,
) -> list[tuple[UUID, UUID]]:
    """Finalize expired timed attempts for one candidate (idempotent).

    Args:
        session: Async database session.
        candidate_id: Candidate whose attempts to scan.
        assessment_id: Optional single module filter.
        now: Clock override for tests.
        enqueue: When True, queue post-submit scoring for each new completion.

    Returns:
        ``(candidate_id, assessment_id)`` pairs newly marked completed.
    """
    expired = await list_expired_in_progress(
        session, now=now, candidate_id=candidate_id
    )
    if assessment_id is not None:
        expired = [(p, a) for p, a in expired if p.assessment_id == assessment_id]
    if not expired:
        return []

    candidate = (
        await session.execute(
            select(Candidate).where(
                Candidate.id == candidate_id,
                Candidate.deleted_at.is_(None),
            )
        )
    ).scalar_one_or_none()
    if candidate is None:
        return []

    finalized: list[tuple[UUID, UUID]] = []
    for progress, _assessment in expired:
        stamp = getattr(progress, "expires_at", None) or (now or request_clock(session))
        claimed = await finalize_one_expired(
            session,
            candidate=candidate,
            assessment_id=progress.assessment_id,
            completed_at=stamp,
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


async def claim_expired_in_progress(
    session: AsyncSession,
    *,
    now: datetime | None = None,
    limit: int = EXPIRY_SWEEP_BATCH_LIMIT,
) -> list[CandidateProgress]:
    """Lock up to ``limit`` expired ``IN_PROGRESS`` rows, skipping busy ones.

    Uses the partial index on ``expires_at`` (status = IN_PROGRESS) instead of
    loading every in-progress attempt. ``SKIP LOCKED`` passes over rows that an
    autosave / submit currently holds; that request finalizes them itself, or
    the next sweep does. The locks only last until the first per-row commit;
    double-finalize is prevented by ``submit_test``'s own ``FOR UPDATE``.

    Args:
        session: Async database session.
        now: Clock override for tests; defaults to the database ``now()`` so
            app-node clock skew cannot move the deadline.
        limit: Max rows per sweep.

    Returns:
        Locked progress rows, earliest deadline first.
    """
    cutoff = now if now is not None else func.now()
    stmt = (
        select(CandidateProgress)
        .where(
            CandidateProgress.status == IN_PROGRESS_STATUS,
            CandidateProgress.expires_at.is_not(None),
            CandidateProgress.expires_at <= cutoff,
        )
        .order_by(CandidateProgress.expires_at)
        .limit(limit)
        .with_for_update(skip_locked=True)
    )
    return list((await session.execute(stmt)).scalars().all())


async def finalize_expired_assessments(
    session: AsyncSession,
    *,
    now: datetime | None = None,
    enqueue: bool = True,
    limit: int = EXPIRY_SWEEP_BATCH_LIMIT,
) -> list[tuple[UUID, UUID]]:
    """Idempotently complete expired ``IN_PROGRESS`` timed attempts (one batch).

    Uses the same scoring / Gemini / PDF pipeline as a normal candidate
    submit (``enqueue_finalize_and_score_ai``). Each row is isolated: an
    error on one attempt is logged and the sweep moves on.

    Args:
        session: Async database session (``submit_test`` commits per row).
        now: Clock override for tests.
        enqueue: When True, queue post-submit scoring for each new completion.
        limit: Max rows handled in this batch.

    Returns:
        ``(candidate_id, assessment_id)`` pairs newly marked completed.
    """
    expired = await claim_expired_in_progress(session, now=now, limit=limit)
    if not expired:
        return []

    candidate_ids = {progress.candidate_id for progress in expired}
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
    for progress in expired:
        candidate_id = progress.candidate_id
        assessment_id = progress.assessment_id
        candidate = by_id.get(candidate_id)
        if candidate is None:
            logger.warning(
                "expiry_skip_missing_candidate progress_id=%s candidate_id=%s",
                progress.id,
                candidate_id,
            )
            continue
        stamp = getattr(progress, "expires_at", None) or (now or request_clock(session))
        try:
            claimed = await finalize_one_expired(
                session,
                candidate=candidate,
                assessment_id=assessment_id,
                completed_at=stamp,
            )
            if not claimed:
                continue
            finalized.append((candidate.id, assessment_id))
            if enqueue:
                await enqueue_finalize_and_score_ai(candidate.id, assessment_id)
        except Exception:
            # One poisoned row (closed package, deleted module, ...) must
            # never stop the rest of the batch.
            logger.exception(
                "expiry_finalize_row_failed candidate_id=%s assessment_id=%s",
                candidate_id,
                assessment_id,
                extra={"event": "expiry_finalize_row_failed"},
            )
            with contextlib.suppress(Exception):
                await session.rollback()
            continue
        logger.info(
            "assessment_auto_finalized candidate_id=%s assessment_id=%s",
            candidate.id,
            assessment_id,
        )
    return finalized


async def ensure_expired_assessments_finalized() -> int:
    """Best-effort sweep in its own session (ARQ cron / ops endpoint).

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
