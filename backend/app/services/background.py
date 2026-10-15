"""Background helpers that need their own DB session."""
from __future__ import annotations

import logging
from uuid import UUID

from app.database import SessionLocal
from app.services.candidate_service import CandidateService
from app.services.gemini_client import background_retry_profile

logger = logging.getLogger(__name__)


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
