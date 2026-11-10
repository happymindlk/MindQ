"""Persist and load pre-computed MindQ Report JSON for instant View Report."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.candidate import Candidate
from app.models.candidate_report import CandidateReport
from app.schemas.mindq_report import MindQReportResponse
from app.services.report_cache import report_cache_key

logger = logging.getLogger(__name__)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


async def read_report_snapshot(
    session: AsyncSession, candidate_id: UUID
) -> MindQReportResponse | None:
    """Return a cached report payload when one exists and is viewable.

    Args:
        session: Async database session.
        candidate_id: Candidate whose snapshot should be loaded.

    Returns:
        Parsed ``MindQReportResponse``, or ``None`` when missing / generating.
    """
    row = (
        await session.execute(
            select(CandidateReport).where(CandidateReport.candidate_id == candidate_id)
        )
    ).scalar_one_or_none()
    if row is None:
        return None
    # Guard against non-CandidateReport rows (e.g. mocked execute side-effects)
    # so View Report falls through to live assembly instead of AttributeError.
    if not hasattr(row, "payload") or not hasattr(row, "synthesis_status"):
        return None
    # Incomplete snapshots must not short-circuit live assembly — HR still needs
    # scores while the narrative is regenerating.
    if row.synthesis_status == "generating":
        return None
    try:
        return MindQReportResponse.model_validate(row.payload)
    except Exception:
        logger.exception(
            "report_snapshot_invalid candidate_id=%s", candidate_id
        )
        return None


async def upsert_report_snapshot(
    session: AsyncSession,
    candidate: Candidate,
    report: MindQReportResponse,
    *,
    pdf_cache_key: str | None = None,
) -> None:
    """Write (or refresh) the pre-computed report JSON for a candidate.

    Args:
        session: Async database session.
        candidate: Candidate the report belongs to.
        report: Fully assembled MindQ Report payload.
        pdf_cache_key: Optional content-addressed PDF storage key.
    """
    if report.synthesis_status == "generating":
        # Do not persist a half-built narrative that would churn on every view.
        return
    payload = report.model_dump(mode="json")
    cache_key = pdf_cache_key or report_cache_key(report).key
    now = _utcnow()
    stmt = (
        insert(CandidateReport)
        .values(
            corporate_id=candidate.corporate_id,
            candidate_id=candidate.id,
            package_id=candidate.package_id,
            payload=payload,
            pdf_cache_key=cache_key,
            synthesis_status=report.synthesis_status,
            generated_at=now,
            updated_at=now,
        )
        .on_conflict_do_update(
            index_elements=["candidate_id"],
            set_={
                "payload": payload,
                "pdf_cache_key": cache_key,
                "synthesis_status": report.synthesis_status,
                "package_id": candidate.package_id,
                "corporate_id": candidate.corporate_id,
                "updated_at": now,
            },
        )
    )
    await session.execute(stmt)
    await session.commit()
    logger.info(
        "report_snapshot_upserted candidate_id=%s synthesis_status=%s",
        candidate.id,
        report.synthesis_status,
    )
