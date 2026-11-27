"""Set-based progress aggregates (replaces per-candidate N+1 loops, P1-17)."""
from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.assessment import Assessment
from app.models.candidate_progress import CandidateProgress


@dataclass(frozen=True)
class ProgressSummary:
    """Per-candidate counts across all of their modules."""

    completed: int = 0
    in_progress: int = 0
    avg_score: float | None = None


async def progress_summaries(
    session: AsyncSession, candidate_ids: Iterable[UUID]
) -> dict[UUID, ProgressSummary]:
    """One GROUP BY query for many candidates' progress counts.

    Args:
        session: Async database session.
        candidate_ids: Candidates to summarize.

    Returns:
        ``candidate_id -> ProgressSummary``; candidates with no progress rows
        are absent (callers default to ``ProgressSummary()``).
    """
    ids = list(dict.fromkeys(candidate_ids))
    if not ids:
        return {}
    stmt = (
        select(
            CandidateProgress.candidate_id,
            func.count().filter(CandidateProgress.status == "COMPLETED"),
            func.count().filter(CandidateProgress.status == "IN_PROGRESS"),
            func.avg(CandidateProgress.score),
        )
        .where(CandidateProgress.candidate_id.in_(ids))
        .group_by(CandidateProgress.candidate_id)
    )
    out: dict[UUID, ProgressSummary] = {}
    for candidate_id, completed, in_progress, avg in (await session.execute(stmt)).all():
        out[candidate_id] = ProgressSummary(
            completed=int(completed or 0),
            in_progress=int(in_progress or 0),
            avg_score=float(avg) if avg is not None else None,
        )
    return out


async def assessment_counts(
    session: AsyncSession, package_ids: Iterable[UUID]
) -> dict[UUID, int]:
    """One GROUP BY query for module counts per package.

    Args:
        session: Async database session.
        package_ids: Packages to count.

    Returns:
        ``package_id -> number of assessments`` (absent means 0).
    """
    ids = list(dict.fromkeys(package_ids))
    if not ids:
        return {}
    stmt = (
        select(Assessment.package_id, func.count(Assessment.id))
        .where(Assessment.package_id.in_(ids))
        .group_by(Assessment.package_id)
    )
    return {pkg: int(n) for pkg, n in (await session.execute(stmt)).all()}
