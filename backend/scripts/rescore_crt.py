"""Recompute stored scores for assessments containing CRT items.

CRT answer keys pasted as one quoted list (``'"5", "5 cents"'``) were matched
literally, so correct answers scored 0. Scoring now splits those keys; this
script brings stored ``candidate_progress.score`` in line with it.

Usage (from backend/ with venv active):
  python -m scripts.rescore_crt            # dry run: report changes only
  python -m scripts.rescore_crt --apply    # write scores, flag JD evals for regeneration

JD-fit evaluations of affected candidates were generated from the wrong score,
so ``--apply`` clears their ``jd_hash``; the next report read regenerates them
(the stale payload stays visible until then).
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from decimal import Decimal

from sqlalchemy import select, update

from app.database import SessionLocal
from app.models.assessment import Assessment
from app.models.candidate_evaluation import CandidateEvaluation
from app.models.candidate_progress import CandidateProgress
from app.models.candidate_response import CandidateResponse
from app.services.scoring import score_assessment_detailed

COMPLETED = "COMPLETED"


def _has_crt(assessment: Assessment) -> bool:
    return any(
        isinstance(q, dict) and str(q.get("type", "")).lower() == "crt"
        for q in assessment.questions or []
    )


def _as_float(value: Decimal | float | None) -> float | None:
    return None if value is None else float(value)


async def rescore(apply: bool) -> int:
    """Recompute CRT-bearing assessment scores.

    Args:
        apply: Persist changes when True; report only when False.

    Returns:
        Number of progress rows whose score changed.
    """
    async with SessionLocal() as session:
        assessments = [a for a in (await session.execute(select(Assessment))).scalars() if _has_crt(a)]
        print(f"assessments with CRT items: {len(assessments)}")
        changed = 0
        affected_candidates: set = set()
        for assessment in assessments:
            progresses = (
                await session.execute(
                    select(CandidateProgress).where(
                        CandidateProgress.assessment_id == assessment.id,
                        CandidateProgress.status == COMPLETED,
                    )
                )
            ).scalars().all()
            for progress in progresses:
                responses = (
                    await session.execute(
                        select(CandidateResponse).where(
                            CandidateResponse.candidate_id == progress.candidate_id,
                            CandidateResponse.assessment_id == assessment.id,
                        )
                    )
                ).scalars().all()
                result = score_assessment_detailed(assessment.questions, responses)
                old = _as_float(progress.score)
                if old == result.score:
                    continue
                changed += 1
                affected_candidates.add(progress.candidate_id)
                print(
                    f"  {assessment.title!r} candidate={progress.candidate_id} "
                    f"score {old} -> {result.score}"
                )
                if apply:
                    progress.score = result.score
                    progress.facet_scores = result.facet_scores or None

        stale_evals = 0
        if affected_candidates:
            stale_evals = len(
                (
                    await session.execute(
                        select(CandidateEvaluation.id).where(
                            CandidateEvaluation.candidate_id.in_(affected_candidates),
                            CandidateEvaluation.status == "ok",
                        )
                    )
                ).all()
            )
            if apply and stale_evals:
                await session.execute(
                    update(CandidateEvaluation)
                    .where(CandidateEvaluation.candidate_id.in_(affected_candidates))
                    .values(jd_hash="")
                )
        if apply:
            await session.commit()
        else:
            await session.rollback()
        mode = "applied" if apply else "dry run"
        print(
            f"{mode}: {changed} score(s) changed across {len(affected_candidates)} candidate(s); "
            f"{stale_evals} JD evaluation(s) {'flagged for regeneration' if apply else 'would be flagged'}"
        )
        return changed


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--apply", action="store_true", help="persist recomputed scores")
    args = parser.parse_args()
    asyncio.run(rescore(args.apply))
    return 0


if __name__ == "__main__":
    sys.exit(main())
