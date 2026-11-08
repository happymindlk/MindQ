"""MindQ Report data for on-screen preview and client-side PDF export."""
from __future__ import annotations

from types import SimpleNamespace
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
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
from app.schemas.jd_evaluation import ReportNarrative
from app.schemas.mindq_report import (
    MindQReportResponse,
    ReportCustomQuestion,
    SynthesisStatus,
    role_alignment_for_report,
)
from app.security import enforce_user_rate_limit, report_view_limiter
from app.services.background import (
    claim_report_refresh,
    is_ai_job_inflight,
    refresh_report_synthesis,
)
from app.services.client_package import PSYCHOMETRIC, TECHNICAL, _strip_answer_keys
from app.services.jd_scoring import CachedSynthesis, JdScoringService
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
    background_tasks: BackgroundTasks,
    hr: HRUserContext = Depends(get_current_hr_user),
    db: AsyncSession = Depends(get_db),
):
    """Return the MindQ Report for on-screen preview and PDF export.

    Psychometric modules contribute module-level scores only; item responses,
    trait facets, and answer keys are omitted. No fit score or hiring
    recommendation is produced. Never waits on Gemini: a missing narrative is
    queued in the background and reported as ``synthesis_status="generating"``.

    Args:
        candidate_id: ``candidates.id`` (not ``candidate_progress.id``).
        background_tasks: Queue for narrative regeneration.
        hr: Authenticated HR or ops user.
        db: Async database session.

    Returns:
        The MindQ Report payload.
    """
    enforce_user_rate_limit(report_view_limiter, hr.user_id, "report_data")
    candidate = (
        await db.execute(select(Candidate).where(Candidate.id == candidate_id))
    ).scalar_one_or_none()
    if not candidate:
        raise HTTPException(status_code=404, detail="Candidate not found")

    if not is_ops_role(hr.role) and candidate.corporate_id != hr.corporate_id:
        raise HTTPException(status_code=403, detail="Forbidden")

    return await build_technical_report_data(db, candidate, background_tasks)


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
                derived_profile=getattr(row, "derived_profile", None),
                score_details=getattr(row, "score_details", None),
                overtime=bool(getattr(row, "overtime", False)),
            )
        )
    return coerced


def _resolve_synthesis_status(
    candidate_id: UUID,
    cached: CachedSynthesis,
    *,
    missing_open_evals: bool,
    background_tasks: BackgroundTasks,
) -> SynthesisStatus:
    """Map the cache state to an API status, queueing a refresh when one is due.

    Args:
        candidate_id: Candidate being reported on.
        cached: Read-only cache lookup result.
        missing_open_evals: Whether technical open-ended items still lack a grade.
        background_tasks: Request-scoped task queue.

    Returns:
        ``ok``/``skipped`` from the cache, ``generating`` while a job is running
        or was just queued, otherwise ``failed``.
    """
    wants_refresh = cached.needs_refresh or missing_open_evals
    if cached.state in ("ok", "skipped"):
        if missing_open_evals and claim_report_refresh(candidate_id):
            background_tasks.add_task(refresh_report_synthesis, candidate_id)
        return cached.state
    if is_ai_job_inflight(candidate_id):
        return "generating"
    if wants_refresh and claim_report_refresh(candidate_id):
        background_tasks.add_task(refresh_report_synthesis, candidate_id)
        return "generating"
    return "failed"


async def build_technical_report_data(
    db: AsyncSession, candidate: Candidate, background_tasks: BackgroundTasks
) -> MindQReportResponse:
    """Assemble the MindQ Report for an already-authorized candidate.

    Callers MUST verify tenant access before calling. Only reads the database:
    missing open-ended technical grades and a missing, stale, or failed
    synthesis are regenerated by ``refresh_report_synthesis`` on
    ``background_tasks``, and the response reports ``generating`` meanwhile.

    Args:
        db: Async database session.
        candidate: Candidate row the caller is allowed to read.
        background_tasks: Request-scoped queue for narrative regeneration.

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
    missing_open_evals = TechnicalEvalService.has_missing_open_evals(
        assessments, responses_by_assessment
    )

    catalog = await load_catalog_categories(db, assessments)
    progress_for_report = _progress_with_facet_scores(assessments, progress_rows)
    outcomes = build_module_outcomes(
        assessments,
        progress_for_report,
        response_rows,
        catalog,
    )
    scores_released = bool(outcomes) and all(o.scores_released for o in outcomes)

    synthesis: ReportNarrative | None = None
    synthesis_status: SynthesisStatus = "pending"
    if scores_released:
        cached = await JdScoringService.read_cached(
            db, candidate=candidate, package=package, outcomes=outcomes
        )
        synthesis = cached.narrative
        synthesis_status = _resolve_synthesis_status(
            candidate.id,
            cached,
            missing_open_evals=missing_open_evals,
            background_tasks=background_tasks,
        )
    elif missing_open_evals and claim_report_refresh(candidate.id):
        background_tasks.add_task(refresh_report_synthesis, candidate.id)

    released = bool(synthesis and scores_released)
    summaries = performance_summaries(candidate.full_name, outcomes, synthesis)
    breakdown = build_competency_breakdown(outcomes, summaries, synthesis)

    # Header counter must match the competency cards actually rendered — never
    # count a COMPLETED-but-unscored module that the breakdown silently drops.
    # While scores are withheld the breakdown lists every package module, so
    # fall back to finalized attempts only.
    completed_times = [
        o.completed_at
        for o in outcomes
        if o.status in {"COMPLETED", "TIMED_OUT"} and o.completed_at is not None
    ]
    completed_count = (
        len(breakdown)
        if scores_released
        else sum(1 for o in outcomes if o.status in {"COMPLETED", "TIMED_OUT"})
    )
    return MindQReportResponse(
        candidate_id=candidate.id,
        company_name=corporate.name if corporate else "",
        company_logo_url=_safe_logo_url(getattr(corporate, "logo_url", None) if corporate else None),
        completed_at=max(completed_times) if completed_times and scores_released else None,
        synthesis_status=synthesis_status,
        candidate_full_name=candidate.full_name,
        candidate_email=candidate.email,
        target_role=(package.target_role or package.title or "") if package else "",
        total_assessments_completed=completed_count,
        category_averages=compute_category_averages(outcomes),
        headline=(synthesis.headline if released else ""),
        key_takeaways=(synthesis.key_takeaways if released else []),
        executive_summary=(synthesis.executive_summary if released else ""),
        role_alignment=(
            role_alignment_for_report(synthesis.role_alignment) if released else []
        ),
        strengths=(synthesis.strengths if released else []),
        areas_to_explore=(synthesis.areas_to_explore if released else []),
        work_environment_notes=(synthesis.work_environment_notes if released else []),
        interview_focus_areas=(synthesis.interview_focus_areas if released else []),
        verify_separately=(synthesis.verify_separately if released else []),
        support_suggestions=(synthesis.support_suggestions if released else []),
        reliability_notes=(synthesis.reliability_notes if released else []),
        competency_breakdown=breakdown,
        category_summaries=(
            build_category_summaries(candidate.full_name, outcomes, synthesis)
            if scores_released
            else []
        ),
        custom_questions=(
            _custom_questions(assessments, responses_by_assessment, summaries)
            if scores_released
            else []
        ),
    )
