"""Background helpers that need their own DB session."""
from __future__ import annotations

import logging
from datetime import datetime
from uuid import UUID

from app.database import SessionLocal
from app.models.candidate_progress import CandidateProgress
from app.models.corporate import Corporate
from app.services.candidate_service import CandidateService
from app.services.email_service import EmailService
from app.services.gemini_client import background_retry_profile
from app.services.package_service import PackageService
from sqlalchemy import select

logger = logging.getLogger(__name__)


async def persist_assessment_started(
    candidate_id: UUID,
    assessment_id: UUID,
    corporate_id: UUID,
    started_at: datetime,
) -> None:
    """Legacy helper: attempt start is now synchronous via ``POST /test/.../start``.

    Kept for any in-flight BackgroundTasks queued before the cutover. Safe no-op
    when ``started_at`` is already set.

    Args:
        candidate_id: Candidate opening the module.
        assessment_id: Assessment being started.
        corporate_id: Tenant id for a new progress row.
        started_at: Clock start already shown to the candidate.
    """
    async with SessionLocal() as session:
        try:
            progress = (
                await session.execute(
                    select(CandidateProgress).where(
                        CandidateProgress.candidate_id == candidate_id,
                        CandidateProgress.assessment_id == assessment_id,
                    )
                )
            ).scalars().first()
            if progress is not None and progress.started_at is not None:
                return
            if progress is None:
                session.add(
                    CandidateProgress(
                        corporate_id=corporate_id,
                        candidate_id=candidate_id,
                        assessment_id=assessment_id,
                        status="IN_PROGRESS",
                        started_at=started_at,
                    )
                )
            else:
                progress.status = "IN_PROGRESS"
                progress.started_at = started_at
            await session.commit()
        except Exception:
            logger.exception(
                "persist_assessment_started_failed candidate_id=%s assessment_id=%s",
                candidate_id,
                assessment_id,
            )


async def finalize_and_score_ai(
    candidate_id: UUID, assessment_id: UUID
) -> None:
    """Backfill core scores if needed, then run Gemini technical + JD pipelines.

    Core facet scoring normally lands in the submit transaction. This task is
    the safety net plus the LLM / HR side-effects that must not block the
    candidate HTTP response.

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
    with background_retry_profile():
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


async def score_jd_for_candidate(candidate_id: UUID) -> None:
    """Backward-compatible alias used by older call sites."""
    await score_ai_for_candidate(candidate_id)
