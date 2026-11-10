"""Background helpers that need their own DB session."""
from __future__ import annotations

import logging
import time
from collections.abc import Iterator
from contextlib import contextmanager
from uuid import UUID

from app.database import SessionLocal
from app.models.assessment import Assessment
from app.models.candidate_progress import CandidateProgress
from app.models.candidate_response import CandidateResponse
from app.models.corporate import Corporate
from app.services.candidate_service import CandidateService
from app.services.email_service import EmailService
from app.services.gemini_client import background_retry_profile
from app.services.jd_scoring import FAILED_RETRY_COOLDOWN
from app.services.package_service import PackageService
from app.services.technical_eval import TechnicalEvalService
from sqlalchemy import select

logger = logging.getLogger(__name__)

# Per-candidate count of running AI jobs. In-process only, matching the
# single-worker assumption already made by ``app.security.RateLimiter``; with
# several workers a duplicate run costs one extra Gemini call but stays
# correct because writes are keyed on the synthesis cache digest.
_ai_jobs_inflight: dict[UUID, int] = {}
# Monotonic time of the last view-triggered refresh. Failed technical grades
# stay "missing" so they can be retried; without this cooldown every report
# poll would re-queue a Gemini grading run for a persistently failing item.
_last_view_refresh: dict[UUID, float] = {}


@contextmanager
def _track_ai_job(candidate_id: UUID) -> Iterator[None]:
    _ai_jobs_inflight[candidate_id] = _ai_jobs_inflight.get(candidate_id, 0) + 1
    try:
        yield
    finally:
        remaining = _ai_jobs_inflight.get(candidate_id, 1) - 1
        if remaining <= 0:
            _ai_jobs_inflight.pop(candidate_id, None)
        else:
            _ai_jobs_inflight[candidate_id] = remaining


def is_ai_job_inflight(candidate_id: UUID) -> bool:
    """Whether a grading or synthesis job is currently running for a candidate.

    Args:
        candidate_id: Candidate to check.

    Returns:
        True while ``score_ai_for_candidate`` or ``refresh_report_synthesis``
        is running for this candidate in this process.
    """
    return _ai_jobs_inflight.get(candidate_id, 0) > 0


def claim_report_refresh(candidate_id: UUID, *, now: float | None = None) -> bool:
    """Reserve a view-triggered refresh slot for a candidate.

    Args:
        candidate_id: Candidate whose report is being viewed.
        now: Monotonic clock override (tests).

    Returns:
        True when the caller should queue ``refresh_report_synthesis``; False
        when a job is already running or one was queued within the cooldown.
    """
    if is_ai_job_inflight(candidate_id):
        return False
    current = time.monotonic() if now is None else now
    cooldown = FAILED_RETRY_COOLDOWN.total_seconds()
    for key, claimed_at in list(_last_view_refresh.items()):
        if current - claimed_at >= cooldown:
            _last_view_refresh.pop(key, None)
    if candidate_id in _last_view_refresh:
        return False
    _last_view_refresh[candidate_id] = current
    return True


async def finalize_and_score_ai(
    candidate_id: UUID, assessment_id: UUID
) -> None:
    """Apply core scores, then run Gemini technical + JD pipelines.

    Core facet scoring is deferred from the submit HTTP path so candidates
    get a fast 200. This task persists scores then runs LLM / HR side-effects.

    Args:
        candidate_id: Candidate who just submitted.
        assessment_id: Assessment that was submitted.
    """
    async with SessionLocal() as session:
        candidate = await CandidateService.get_candidate(session, candidate_id)
        if not candidate:
            logger.warning("finalize_missing_candidate id=%s", candidate_id)
            return
        try:
            await CandidateService.finalize_submission_scores(
                session, candidate, assessment_id
            )
        except Exception:
            logger.exception(
                "finalize_scores_failed candidate_id=%s assessment_id=%s",
                candidate_id,
                assessment_id,
            )

    await score_ai_for_candidate(candidate_id, assessment_id)
    await notify_hr_if_package_complete(candidate_id)
    await prewarm_report_pdf(candidate_id)


async def notify_hr_if_package_complete(candidate_id: UUID) -> None:
    """Send the HR completion email only after the full package is done.

    Kept off the submit hot path so package/corporate lookups never delay
    the candidate's HTTP response.

    Args:
        candidate_id: Candidate who just submitted a module.
    """
    async with SessionLocal() as session:
        try:
            candidate = await CandidateService.get_candidate(session, candidate_id)
            if not candidate:
                return
            if not await CandidateService.is_package_complete(session, candidate):
                return
            package = await PackageService.get_package(session, candidate.package_id)
            corporate = (
                await session.execute(
                    select(Corporate).where(Corporate.id == candidate.corporate_id)
                )
            ).scalar_one_or_none()
            if not corporate or not corporate.contact_email:
                return
            await EmailService.send_hr_completion_email(
                corporate.contact_email,
                candidate_name=candidate.full_name,
                candidate_email=candidate.email,
                package_title=package.title if package else "assessment package",
                hr_name=corporate.name,
            )
        except Exception:
            logger.exception("hr_completion_email_failed candidate_id=%s", candidate_id)


async def score_ai_for_candidate(
    candidate_id: UUID, assessment_id: UUID | None = None
) -> None:
    """Grade custom technical items, then JD-fit if the package is complete.

    Runs after test submit without blocking the candidate. Technical items are
    evaluated sequentially (free-tier RPM). JD scoring still waits until every
    assessment is submitted.

    Args:
        candidate_id: Candidate who just submitted.
        assessment_id: Assessment that was submitted (item-level Gemini).
    """
    with _track_ai_job(candidate_id), background_retry_profile():
        async with SessionLocal() as session:
            candidate = await CandidateService.get_candidate(session, candidate_id)
            if not candidate:
                logger.warning("ai_background_missing_candidate id=%s", candidate_id)
                return
            try:
                if assessment_id is not None:
                    await CandidateService.evaluate_technical_if_needed(
                        session, candidate, assessment_id
                    )
            except Exception:
                logger.exception(
                    "technical_eval_background_failed candidate_id=%s assessment_id=%s",
                    candidate_id,
                    assessment_id,
                )
            try:
                await CandidateService.evaluate_jd_if_package_complete(session, candidate)
            except Exception:
                logger.exception("jd_background_failed candidate_id=%s", candidate_id)


async def refresh_report_synthesis(candidate_id: UUID) -> None:
    """Regenerate missing technical grades and the report synthesis off the request path.

    Queued by report views when the cached synthesis is missing, stale, or
    failed past its cooldown. Technical grades run first because the synthesis
    cache key covers technical scores; grading afterwards would immediately
    invalidate the narrative. Skips when another AI job for this candidate is
    already running so report polling cannot stack duplicate Gemini calls.

    Args:
        candidate_id: Candidate whose report is being viewed.
    """
    if is_ai_job_inflight(candidate_id):
        logger.info("report_synthesis_refresh_skipped_inflight candidate_id=%s", candidate_id)
        return
    with _track_ai_job(candidate_id), background_retry_profile():
        async with SessionLocal() as session:
            candidate = await CandidateService.get_candidate(session, candidate_id)
            if not candidate:
                logger.warning("report_synthesis_refresh_missing_candidate id=%s", candidate_id)
                return
            try:
                assessments = list(
                    (
                        await session.execute(
                            select(Assessment)
                            .where(Assessment.package_id == candidate.package_id)
                            .order_by(Assessment.position)
                        )
                    ).scalars().all()
                )
                responses = (
                    await session.execute(
                        select(CandidateResponse).where(
                            CandidateResponse.candidate_id == candidate.id
                        )
                    )
                ).scalars().all()
                responses_by_assessment: dict[UUID, dict[str, object]] = {}
                for row in responses:
                    responses_by_assessment.setdefault(row.assessment_id, {})[
                        str(row.question_id)
                    ] = row.response
                if TechnicalEvalService.has_missing_open_evals(
                    assessments, responses_by_assessment
                ):
                    progress_rows = list(
                        (
                            await session.execute(
                                select(CandidateProgress).where(
                                    CandidateProgress.candidate_id == candidate.id
                                )
                            )
                        ).scalars().all()
                    )
                    await TechnicalEvalService.evaluate_candidate(
                        session,
                        candidate=candidate,
                        assessments=assessments,
                        progress_rows=progress_rows,
                    )
            except Exception:
                logger.exception(
                    "report_technical_backfill_failed candidate_id=%s", candidate_id
                )
                await session.rollback()
            try:
                await CandidateService.evaluate_jd_if_package_complete(session, candidate)
            except Exception:
                logger.exception("report_synthesis_refresh_failed candidate_id=%s", candidate_id)
    await prewarm_report_pdf(candidate_id)


async def prewarm_report_pdf(candidate_id: UUID) -> None:
    """Compile and cache the MindQ Report PDF once the package is complete.

    Runs after scoring / synthesis so HR and candidate downloads hit storage
    instead of waiting on WeasyPrint. No-ops when the package is incomplete or
    the narrative is still generating (that payload would churn the cache key).

    Args:
        candidate_id: Candidate whose package may just have finished.
    """
    from app.api.v1.candidate_reports import assemble_technical_report_data
    from app.services.report_cache import report_cache_key
    from app.services.report_pdf import render_and_store_report
    from app.services.report_snapshot import upsert_report_snapshot

    class _NoopBackgroundTasks:
        """Drop view-side synthesis queues; this warmer never starts new LLM work."""

        def add_task(self, *_args, **_kwargs) -> None:
            return None

    try:
        async with SessionLocal() as session:
            candidate = await CandidateService.get_candidate(session, candidate_id)
            if not candidate:
                return
            if not await CandidateService.is_package_complete(session, candidate):
                return
            # Always assemble fresh here so the snapshot and PDF reflect the
            # latest scores / narrative (bypass read_report_snapshot).
            report = await assemble_technical_report_data(
                session, candidate, _NoopBackgroundTasks()
            )
            if report.synthesis_status == "generating":
                logger.info(
                    "report_pdf_prewarm_skipped_generating candidate_id=%s", candidate_id
                )
                return
            await upsert_report_snapshot(session, candidate, report)
            await render_and_store_report(
                report,
                corporate_id=candidate.corporate_id,
                candidate_id=candidate.id,
                portal="admin",
            )
            logger.info(
                "report_pdf_prewarm_ok candidate_id=%s cache_key=%s",
                candidate_id,
                report_cache_key(report).key[:12],
            )
    except Exception:
        logger.exception("report_pdf_prewarm_failed candidate_id=%s", candidate_id)


async def score_jd_for_candidate(candidate_id: UUID) -> None:
    """Backward-compatible alias used by older call sites."""
    await score_ai_for_candidate(candidate_id)
