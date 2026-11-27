"""ARQ task entrypoints — thin wrappers over existing service helpers."""
from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any
from uuid import UUID

from arq import Retry
from arq.worker import func
from starlette.concurrency import run_in_threadpool

from app.config import settings
from app.services.background import (
    ScoringFailedError,
    finalize_and_score_ai,
    find_unscored_completed,
    refresh_report_synthesis,
)
from app.services.email import send_transactional_email
from app.services.email_service import EmailService
from app.sentry_init import capture_silent_failure
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

    Under the ARQ worker a core-scoring failure raises ``arq.Retry`` with
    linear backoff until ``ARQ_MAX_TRIES``; the last failure is re-raised so
    the job is recorded as failed (the reconciler cron re-queues it later).
    Inline runs (no Redis, ``ctx == {}``) log and return, as before.

    Args:
        ctx: ARQ worker context (``job_try`` present when run by the worker).
        candidate_id: Candidate who submitted.
        assessment_id: Assessment that was submitted.

    Raises:
        arq.Retry: Scoring failed and retries remain.
        ScoringFailedError: Scoring failed on the final ARQ try.
    """
    job_try = ctx.get("job_try") if ctx else None
    try:
        await finalize_and_score_ai(_as_uuid(candidate_id), _as_uuid(assessment_id))
    except ScoringFailedError:
        if job_try is None:
            return  # inline fallback: already logged; reconciler covers it
        if job_try < settings.ARQ_MAX_TRIES:
            raise Retry(defer=timedelta(seconds=30 * job_try))
        raise


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


async def task_finalize_expired_assessment(
    ctx: dict[str, Any],
    candidate_id: UUID | str,
    assessment_id: UUID | str | None = None,
) -> int:
    """Finalize one candidate's expired timed attempt(s) and enqueue scoring.

    Args:
        ctx: ARQ worker context.
        candidate_id: Candidate whose in-progress modules to scan.
        assessment_id: Optional single module filter.

    Returns:
        Number of modules newly finalized.
    """
    del ctx
    from app.database import SessionLocal
    from app.services.assessment_expiry import finalize_expired_assessment

    async with SessionLocal() as session:
        finalized = await finalize_expired_assessment(
            session,
            _as_uuid(candidate_id),
            assessment_id=_as_uuid(assessment_id) if assessment_id else None,
            enqueue=True,
        )
    return len(finalized)


async def task_sweep_expired_assessments(ctx: dict[str, Any]) -> int:
    """Periodic safety sweep for abandoned timed assessments.

    Args:
        ctx: ARQ worker context.

    Returns:
        Number of modules newly finalized.
    """
    del ctx
    from app.services.assessment_expiry import ensure_expired_assessments_finalized

    return await ensure_expired_assessments_finalized()


async def task_reconcile_unscored(ctx: dict[str, Any]) -> int:
    """Re-queue scoring for COMPLETED attempts that have no ``score_details``.

    Safety net for P0-01/P0-02: lost enqueues, exhausted retries, worker
    restarts. Uses the same ``finalize:{cand}:{assess}`` job id as submit, so
    a job that is already queued or retrying is not duplicated.

    Args:
        ctx: ARQ worker context; ``ctx["redis"]`` is the worker's pool.

    Returns:
        Number of jobs newly enqueued.
    """
    from app.jobs.enqueue import _job_id_finalize

    pairs = await find_unscored_completed(
        lookback=timedelta(hours=settings.SCORING_RECONCILE_LOOKBACK_HOURS)
    )
    if not pairs:
        return 0
    redis = ctx["redis"]
    enqueued = 0
    for candidate_id, assessment_id in pairs:
        try:
            job = await redis.enqueue_job(
                task_finalize_and_score_ai.__name__,
                str(candidate_id),
                str(assessment_id),
                _job_id=_job_id_finalize(candidate_id, assessment_id),
            )
        except Exception:
            logger.exception(
                "scoring_reconcile_enqueue_failed candidate_id=%s assessment_id=%s",
                candidate_id,
                assessment_id,
            )
            continue
        if job is not None:
            enqueued += 1
    logger.warning(
        "scoring_reconcile_found unscored=%d enqueued=%d",
        len(pairs),
        enqueued,
        extra={"event": "scoring_reconcile_found"},
    )
    return enqueued


# Right-to-erasure purge gets more attempts than the global ARQ_MAX_TRIES:
# a transient storage outage must not leave a deleted candidate's PDFs behind.
PURGE_MAX_TRIES = 6
PURGE_RETRY_BASE_SECONDS = 60


async def task_purge_candidate_report_files(
    ctx: dict[str, Any],
    corporate_id: UUID | str,
    candidate_id: UUID | str,
) -> int:
    """Delete every stored report object for an erased candidate (P1-16).

    Runs the strict purge in a worker thread. A storage error raises
    ``arq.Retry`` with linear backoff (60s, 120s, ...) up to
    ``PURGE_MAX_TRIES``; the final failure is logged at ERROR and sent to
    Sentry so ops can finish the erasure by hand.

    Args:
        ctx: ARQ worker context (``job_try`` present under the worker).
        corporate_id: Tenant id (object prefix).
        candidate_id: Erased candidate id.

    Returns:
        Number of object keys deleted.

    Raises:
        arq.Retry: Storage failed and attempts remain.
        StoragePurgeError: Storage failed on the final attempt.
    """
    job_try = ctx.get("job_try") if ctx else None
    corp, cand = _as_uuid(corporate_id), _as_uuid(candidate_id)
    try:
        deleted = await run_in_threadpool(
            storage_service.purge_candidate_report_files, corp, cand, strict=True
        )
    except storage_service.StoragePurgeError as exc:
        if job_try is not None and job_try < PURGE_MAX_TRIES:
            logger.warning(
                "erasure_purge_retry candidate_id=%s try=%s", cand, job_try,
                extra={"event": "erasure_purge_retry"},
            )
            raise Retry(defer=timedelta(seconds=PURGE_RETRY_BASE_SECONDS * job_try)) from exc
        logger.error(
            "erasure_purge_failed candidate_id=%s corporate_id=%s tries=%s",
            cand, corp, job_try,
            extra={"event": "erasure_purge_failed"},
        )
        capture_silent_failure(
            "erasure_purge_failed", exc, candidate_id=str(cand), corporate_id=str(corp)
        )
        if job_try is None:
            return 0  # inline fallback: already reported, never crash the caller
        raise
    logger.info(
        "erasure_purge_done candidate_id=%s deleted=%s", cand, deleted,
        extra={"event": "erasure_purge_done"},
    )
    return deleted


TASK_FUNCTIONS = (
    task_finalize_and_score_ai,
    task_refresh_report_synthesis,
    task_dispatch_candidate_invite,
    task_send_package_share,
    task_send_nudge_email,
    task_store_cached_report,
    task_finalize_expired_assessment,
    task_sweep_expired_assessments,
    task_reconcile_unscored,
    func(task_purge_candidate_report_files, max_tries=PURGE_MAX_TRIES),
)
