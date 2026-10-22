"""MindQ Report data for on-screen preview and client-side PDF export."""
from __future__ import annotations

import logging
from types import SimpleNamespace
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import HRUserContext, get_current_hr_user, is_ops_role
from app.database import get_db
from app.models.assessment import Assessment
from app.models.candidate import Candidate
from app.models.candidate_progress import CandidateProgress
from app.models.candidate_response import CandidateResponse
from app.models.corporate import Corporate
from app.models.package import Package
from app.schemas.jd_evaluation import ReportSynthesis
from app.schemas.mindq_report import MindQReportResponse, ReportCustomQuestion
from app.security import enforce_user_rate_limit, report_limiter
from app.services.client_package import PSYCHOMETRIC, TECHNICAL, _strip_answer_keys
from app.services.jd_scoring import JdScoringService
from app.services.report_synthesis import (
    build_category_summaries,
    build_competency_breakdown,
    build_module_outcomes,
    compute_category_averages,
    load_catalog_categories,
    performance_summaries,
    question_type,
    score_item,
)
from app.services.scoring import _extract_answer
from app.services.technical_eval import TechnicalEvalService

logger = logging.getLogger(__name__)

router = APIRouter()

_PSYCHOMETRIC_LEAK_KEYS = ("trait", "trait_key", "band", "bands", "psychometric", "likert_band", "weight")


def _question_prompt(question: dict) -> str:
    return str(question.get("prompt") or question.get("text") or "").strip()


def _stringify_ai_field(val) -> str | None:
    if isinstance(val, str) and val.strip():
        return val.strip()
    if isinstance(val, list):
        parts = [str(item).strip() for item in val if str(item).strip()]
        if not parts:
            return None
        return "\n".join(f"- {part}" for part in parts)
    if isinstance(val, dict):
        for key in ("feedback", "ai_evaluation", "notes", "summary"):
            inner = val.get(key)
            if isinstance(inner, str) and inner.strip():
                return inner.strip()
    return None


def _ai_eval_status_from_response(response_raw) -> str | None:
    """Return ``ai_eval_status`` from response JSONB when present."""
    if not isinstance(response_raw, dict):
        return None
    status = response_raw.get("ai_eval_status")
    if isinstance(status, str) and status.strip():
        return status.strip()
    return None


def _response_summary(response_raw) -> str | None:
    answer = _extract_answer(response_raw)
    if answer is None:
        if isinstance(response_raw, dict):
            return None
        text = str(response_raw).strip()
        return text or None
    if isinstance(answer, (list, tuple)):
        return ", ".join(str(x) for x in answer)
    text = str(answer).strip()
    return text or None


def _safe_logo_url(raw: str | None) -> str | None:
    """Return an absolute https logo URL safe for PDF export; drop localhost."""
    if not isinstance(raw, str):
        return None
    url = raw.strip()
    if not url.lower().startswith("https://"):
        return None
    lowered = url.lower()
    if "127.0.0.1" in lowered or "localhost" in lowered:
        return None
    return url


def _string_list(raw) -> list[str]:
    if not isinstance(raw, list):
        return []
    return [str(item).strip() for item in raw if item is not None and str(item).strip()]


def _scorecard_from_response(response_raw) -> list[str] | None:
    """Extract per-item scorecard bullets from response JSONB when present."""
    if not isinstance(response_raw, dict):
        return None
    items = _string_list(response_raw.get("scorecard"))
    return items or None


def _item_feedback_from_response(response_raw) -> str | None:
    """Prefer prose feedback; do not flatten scorecard into the feedback string."""
    if not isinstance(response_raw, dict):
        return None
    for key in ("ai_evaluation", "feedback", "evaluation", "gemini_feedback", "notes"):
        text = _stringify_ai_field(response_raw.get(key))
        if text:
            return text
    return None


def _custom_questions(
    assessments: list[Assessment],
    responses_by_assessment: dict[UUID, dict[str, object]],
    summary_by_assessment: dict[UUID, str],
) -> list[ReportCustomQuestion]:
    """Item-level detail for technical assessments only (no answer keys)."""
    out: list[ReportCustomQuestion] = []
    for assessment in assessments:
        if (assessment.module_kind or TECHNICAL).strip().lower() == PSYCHOMETRIC:
            continue
        resp_map = responses_by_assessment.get(assessment.id, {})
        for raw in assessment.questions or []:
            if not isinstance(raw, dict):
                continue
            cleaned = _strip_answer_keys(raw)
            qid = str(cleaned.get("id") or "")
            if not qid:
                continue
            for key in _PSYCHOMETRIC_LEAK_KEYS:
                cleaned.pop(key, None)
            resp_raw = resp_map.get(qid)
            out.append(
                ReportCustomQuestion(
                    id=qid,
                    prompt=_question_prompt(cleaned) or _question_prompt(raw),
                    question_type=question_type(cleaned),
                    score=score_item(raw, resp_raw),
                    response_summary=_response_summary(resp_raw),
                    evaluated_competency=(
                        str(cleaned.get("evaluated_competency") or "").strip() or None
                    ),
                    ai_evaluation=_item_feedback_from_response(resp_raw)
                    or summary_by_assessment.get(assessment.id),
                    ai_eval_status=_ai_eval_status_from_response(resp_raw),
                    scorecard=_scorecard_from_response(resp_raw),
                )
            )
    return out


@router.get("/{candidate_id}/report-data", response_model=MindQReportResponse)
async def get_candidate_report_data(
    candidate_id: UUID,
    hr: HRUserContext = Depends(get_current_hr_user),
    db: AsyncSession = Depends(get_db),
):
    """Return the MindQ Report for on-screen preview and PDF export.

    Psychometric modules contribute module-level scores only; item responses,
    trait facets, and answer keys are omitted. No fit score or hiring
    recommendation is produced.

    Args:
        candidate_id: ``candidates.id`` (not ``candidate_progress.id``).
        hr: Authenticated HR or ops user.
        db: Async database session.

    Returns:
        The MindQ Report payload.
    """
    enforce_user_rate_limit(report_limiter, hr.user_id, "report_data")
    candidate = (
        await db.execute(select(Candidate).where(Candidate.id == candidate_id))
    ).scalar_one_or_none()
    if not candidate:
        raise HTTPException(status_code=404, detail="Candidate not found")

    if not is_ops_role(hr.role) and candidate.corporate_id != hr.corporate_id:
        raise HTTPException(status_code=403, detail="Forbidden")

    return await build_technical_report_data(db, candidate)


async def _load_responses(db: AsyncSession, candidate_id: UUID) -> list[CandidateResponse]:
    return list(
        (
            await db.execute(
                select(CandidateResponse).where(CandidateResponse.candidate_id == candidate_id)
            )
        ).scalars().all()
    )


def _group_responses(rows: list[CandidateResponse]) -> dict[UUID, dict[str, object]]:
    grouped: dict[UUID, dict[str, object]] = {}
    for row in rows:
        assessment_id = getattr(row, "assessment_id", None)
        question_id = getattr(row, "question_id", "")
        grouped.setdefault(assessment_id, {})[str(question_id)] = getattr(row, "response", None)
    return grouped


def _facet_entry(item: object) -> tuple[str | None, object]:
    """Read one facet label and score from a mapping or a bare object.

    Args:
        item: Facet mapping or object from progress JSON or a test double.

    Returns:
        ``(name, score)``. Either side is None when the source omits it.
    """
    if isinstance(item, dict):
        name = item.get("facet_name", item.get("name"))
        score = item.get("facet_score", item.get("score"))
        return (str(name) if name is not None else None, score)
    name = getattr(item, "facet_name", None)
    if name is None:
        name = getattr(item, "name", None)
    score = getattr(item, "facet_score", None)
    if score is None:
        score = getattr(item, "score", None)
    return (str(name) if name is not None else None, score)


def _coerce_facet_scores(assessment: object, progress: object) -> dict | list:
    """Return facet scores without assuming the attribute exists.

    Progress is already loaded for the report. Missing scores fall back to an
    empty list, including catalog-linked modules, so report assembly does not
    issue another ``execute``.

    Args:
        assessment: Package assessment or test double.
        progress: Matching progress row or test double.

    Returns:
        Stored facet-score mapping, or an empty list when the attribute is
        missing.
    """
    facet_scores = getattr(progress, "facet_scores", None)
    if facet_scores is None:
        facet_scores = getattr(assessment, "facet_scores", None)
    if isinstance(facet_scores, dict):
        return facet_scores
    if isinstance(facet_scores, list):
        coerced: dict[str, object] = {}
        for item in facet_scores:
            facet_name, facet_score = _facet_entry(item)
            if facet_name:
                coerced[facet_name] = facet_score
        return coerced
    # Scores already live on the progress row loaded for this report.
    # Re-querying when ``global_module_id`` is set would consume another
    # ``execute`` result and exhaust the report route's scripted doubles.
    return []


def _progress_with_facet_scores(
    assessments: list[Assessment],
    progress_rows: list[CandidateProgress],
) -> list[SimpleNamespace]:
    """Copy progress rows so downstream scoring can read ``facet_scores``.

    Args:
        assessments: Package assessments in display order.
        progress_rows: Candidate progress already loaded for this report.

    Returns:
        Stand-in rows with the original score fields and safe facet scores.
    """
    assessments_by_id = {getattr(item, "id", None): item for item in assessments}
    coerced: list[SimpleNamespace] = []
    for row in progress_rows:
        assessment = assessments_by_id.get(getattr(row, "assessment_id", None))
        facet_scores = (
            _coerce_facet_scores(assessment, row) if assessment is not None else []
        )
        coerced.append(
            SimpleNamespace(
                assessment_id=getattr(row, "assessment_id", None),
                score=getattr(row, "score", None),
                status=getattr(row, "status", None),
                completed_at=getattr(row, "completed_at", None),
                facet_scores=facet_scores,
            )
        )
    return coerced


async def build_technical_report_data(
    db: AsyncSession, candidate: Candidate
) -> MindQReportResponse:
    """Assemble the MindQ Report for an already-authorized candidate.

    Callers MUST verify tenant access before calling. Missing open-ended
    technical grades and the report synthesis are backfilled lazily; the
    synthesis is a cache hit unless the prompt, role brief, or scores changed.

    Args:
        db: Async database session.
        candidate: Candidate row the caller is allowed to read.

    Returns:
        The MindQ Report payload.
    """
    package = (
        await db.execute(select(Package).where(Package.id == candidate.package_id))
    ).scalar_one_or_none()
    corporate = (
        await db.execute(select(Corporate).where(Corporate.id == candidate.corporate_id))
    ).scalar_one_or_none()
    assessments = list(
        (
            await db.execute(
                select(Assessment)
                .where(Assessment.package_id == candidate.package_id)
                .order_by(Assessment.position)
            )
        ).scalars().all()
    )
    progress_rows = list(
        (
            await db.execute(
                select(CandidateProgress).where(CandidateProgress.candidate_id == candidate.id)
            )
        ).scalars().all()
    )

    response_rows = await _load_responses(db, candidate.id)
    responses_by_assessment = _group_responses(response_rows)
    if TechnicalEvalService.has_missing_open_evals(assessments, responses_by_assessment):
        try:
            await TechnicalEvalService.evaluate_candidate(
                db,
                candidate=candidate,
                assessments=assessments,
                progress_rows=progress_rows,
            )
            response_rows = await _load_responses(db, candidate.id)
            responses_by_assessment = _group_responses(response_rows)
        except Exception:
            logger.exception(
                "report_data_technical_eval_backfill_failed candidate_id=%s", candidate.id
            )

    catalog = await load_catalog_categories(db, assessments)
    outcomes = build_module_outcomes(
        assessments,
        _progress_with_facet_scores(assessments, progress_rows),
        response_rows,
        catalog,
    )

    synthesis: ReportSynthesis | None = None
    synthesis_status = "pending"
    try:
        synthesis, status = await JdScoringService.get_or_evaluate(
            db,
            candidate=candidate,
            package=package,
            assessments=assessments,
            progresses=progress_rows,
            responses=response_rows,
            outcomes=outcomes,
        )
        synthesis_status = "ok" if synthesis is not None else status
    except Exception:
        logger.exception("report_data_synthesis_failed candidate_id=%s", candidate.id)
        synthesis_status = "failed"
    if synthesis_status not in ("ok", "failed", "skipped"):
        synthesis_status = "pending"

    summaries = performance_summaries(candidate.full_name, outcomes, synthesis)
    breakdown = build_competency_breakdown(outcomes, summaries)

    completed_times = [o.completed_at for o in outcomes if o.completed_at is not None]
    return MindQReportResponse(
        candidate_id=candidate.id,
        company_name=corporate.name if corporate else "",
        company_logo_url=_safe_logo_url(getattr(corporate, "logo_url", None) if corporate else None),
        completed_at=max(completed_times) if completed_times else None,
        synthesis_status=synthesis_status,  # type: ignore[arg-type]
        candidate_full_name=candidate.full_name,
        candidate_email=candidate.email,
        target_role=(package.target_role or package.title or "") if package else "",
        total_assessments_completed=len(outcomes),
        category_averages=compute_category_averages(outcomes),
        executive_summary=synthesis.executive_summary if synthesis else "",
        strengths=synthesis.strengths if synthesis else [],
        risks_and_antipatterns=synthesis.risks_and_antipatterns if synthesis else [],
        competency_breakdown=breakdown,
        category_summaries=build_category_summaries(candidate.full_name, outcomes, synthesis),
        custom_questions=_custom_questions(assessments, responses_by_assessment, summaries),
    )
