"""MindQ Report data for on-screen preview and client-side PDF export."""
from __future__ import annotations

import logging
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import HRUserContext, get_current_hr_user, is_ops_role
from app.database import get_db
from app.models.assessment import Assessment
from app.models.candidate import Candidate
from app.models.candidate_evaluation import CandidateEvaluation
from app.models.candidate_progress import CandidateProgress
from app.models.candidate_response import CandidateResponse
from app.models.corporate import Corporate
from app.models.global_module import GlobalModule
from app.models.package import Package
from app.schemas.client_package import (
    TechnicalReportCompetency,
    TechnicalReportCustomQuestion,
    TechnicalReportData,
    TechnicalReportModule,
)
from app.schemas.jd_evaluation import RECOMMENDATION_LABELS
from app.services.candidate_service import COMPLETED_STATUS
from app.services.client_package import PSYCHOMETRIC, TECHNICAL, _strip_answer_keys
from app.services.jd_scoring import JdScoringService, evaluation_is_ok
from app.services.report_synthesis import (
    ModuleOutcome,
    build_competency_groups,
    build_completed_assessments,
    module_percentage,
    resolve_category,
)
from app.services.scoring import _extract_answer, _normalize_answer_set
from app.services.technical_eval import TechnicalEvalService

logger = logging.getLogger(__name__)

router = APIRouter()


def _question_prompt(question: dict) -> str:
    return str(question.get("prompt") or question.get("text") or "").strip()


def _question_type(question: dict) -> str:
    raw = question.get("type") or question.get("question_type") or question.get("builder_type")
    return str(raw or "open_ended").lower()


def _ai_score_from_response(response_raw) -> float | None:
    """Gemini item score stored on ``candidate_responses.response`` JSONB."""
    if not isinstance(response_raw, dict):
        return None
    val = response_raw.get("ai_score")
    if isinstance(val, bool) or not isinstance(val, (int, float)):
        return None
    return float(val)


def _score_item(question: dict, response_raw) -> float | None:
    """Return 100/0 for gradable MCQ items; Gemini ``ai_score`` for open-ended."""
    qtype = _question_type(question)
    correct = question.get("correct_answer")
    if correct is None and question.get("correct_answer_or_rubric"):
        # Custom MCQ rows may store the key under the rubric field.
        if qtype == "mcq":
            correct = question.get("correct_answer_or_rubric")
    if qtype == "mcq" and correct is not None:
        expected = _normalize_answer_set(correct)
        if expected:
            given = _normalize_answer_set(_extract_answer(response_raw))
            return 100.0 if given == expected else 0.0
    return _ai_score_from_response(response_raw)


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


def _ai_text_from_response(response_raw) -> str | None:
    """Pull Gemini / grader feedback stored on the response JSONB, if any."""
    if not isinstance(response_raw, dict):
        return None
    for key in (
        "ai_evaluation",
        "feedback",
        "evaluation",
        "scorecard",
        "gemini_feedback",
        "notes",
    ):
        text = _stringify_ai_field(response_raw.get(key))
        if text:
            return text
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


def _notes_by_assessment_title(payload: dict | None) -> dict[str, str]:
    """Map Gemini ``per_assessment[].notes`` keyed by assessment title."""
    out: dict[str, str] = {}
    if not isinstance(payload, dict):
        return out
    for item in payload.get("per_assessment") or []:
        if not isinstance(item, dict):
            continue
        title = str(item.get("title") or "").strip()
        notes = item.get("notes")
        if title and isinstance(notes, str) and notes.strip():
            out[title] = notes.strip()
    return out


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
    out: list[str] = []
    for item in raw:
        text = str(item).strip() if item is not None else ""
        if text:
            out.append(text)
    return out


def _scorecard_from_response(response_raw) -> list[str] | None:
    """Extract Gemini scorecard bullets from response JSONB when present."""
    if not isinstance(response_raw, dict):
        return None
    raw = response_raw.get("scorecard")
    if not isinstance(raw, list):
        return None
    items = _string_list(raw)
    return items or None


def _ai_feedback_from_response(response_raw) -> str | None:
    """Prefer prose feedback; do not flatten scorecard into the feedback string."""
    if not isinstance(response_raw, dict):
        return None
    for key in ("ai_evaluation", "feedback", "evaluation", "gemini_feedback", "notes"):
        text = _stringify_ai_field(response_raw.get(key))
        if text:
            return text
    return None


def _executive_fields(payload: dict | None) -> dict:
    """Pull JD-fit dashboard fields from the Gemini evaluation payload."""
    empty = {
        "overall_fit": None,
        "recommendation_key": None,
        "recommendation_label": None,
        "strengths": [],
        "risks": [],
        "competencies": [],
        "ai_summary": None,
    }
    if not isinstance(payload, dict):
        return empty

    overall_fit = None
    raw_fit = payload.get("overall_fit")
    if isinstance(raw_fit, (int, float)) and not isinstance(raw_fit, bool):
        overall_fit = float(raw_fit)

    key_raw = (
        payload.get("hiring_recommendation")
        or payload.get("recommendation")
        or ""
    )
    key = str(key_raw).strip().lower().replace(" ", "_") or None
    if key and key not in RECOMMENDATION_LABELS:
        # Accept human labels already stored on legacy rows.
        for known, label in RECOMMENDATION_LABELS.items():
            if label.lower() == str(key_raw).strip().lower():
                key = known
                break
        else:
            key = None
    label = RECOMMENDATION_LABELS.get(key) if key else None

    competencies: list[TechnicalReportCompetency] = []
    for item in payload.get("competencies") or []:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "").strip()
        score_raw = item.get("score")
        if not name or not isinstance(score_raw, (int, float)) or isinstance(score_raw, bool):
            continue
        competencies.append(
            TechnicalReportCompetency(name=name, score=float(score_raw))
        )

    ai_summary = None
    for summary_key in ("executive_summary", "summary"):
        raw = payload.get(summary_key)
        if isinstance(raw, str) and raw.strip():
            ai_summary = raw.strip()
            break

    return {
        "overall_fit": overall_fit,
        "recommendation_key": key,
        "recommendation_label": label,
        "strengths": _string_list(payload.get("strengths")),
        "risks": _string_list(payload.get("risks") or payload.get("gaps")),
        "competencies": competencies,
        "ai_summary": ai_summary,
    }


@router.get("/{candidate_id}/report-data", response_model=TechnicalReportData)
async def get_candidate_report_data(
    candidate_id: UUID,
    hr: HRUserContext = Depends(get_current_hr_user),
    db: AsyncSession = Depends(get_db),
):
    """Return MindQ Report fields for on-screen preview and PDF export.

    Psychometric modules contribute module-level scores to the competency
    breakdown only; item responses, trait facets, and answer keys are omitted.
    JD-fit notes are included as ``ai_evaluation`` / ``ai_summary``.

    Args:
        candidate_id: ``candidates.id`` (not ``candidate_progress.id``).
        hr: Authenticated HR or ops user.
        db: Async database session.

    Returns:
        Company/candidate metadata plus technical module and custom-question rows.
    """
    candidate = (
        await db.execute(select(Candidate).where(Candidate.id == candidate_id))
    ).scalar_one_or_none()
    if not candidate:
        raise HTTPException(status_code=404, detail="Candidate not found")

    if not is_ops_role(hr.role) and candidate.corporate_id != hr.corporate_id:
        raise HTTPException(status_code=403, detail="Forbidden")

    return await build_technical_report_data(db, candidate)


async def build_technical_report_data(
    db: AsyncSession, candidate: Candidate
) -> TechnicalReportData:
    """Assemble the MindQ Report for an already-authorized candidate.

    Callers MUST verify tenant access before calling. Missing open-ended
    technical grades and the JD-fit evaluation are backfilled lazily.

    Args:
        db: Async database session.
        candidate: Candidate row the caller is allowed to read.

    Returns:
        Company/candidate metadata, completed assessments, competency groups,
        and technical module / custom-question rows.
    """
    candidate_id = candidate.id
    package = (
        await db.execute(select(Package).where(Package.id == candidate.package_id))
    ).scalar_one_or_none()
    corporate = (
        await db.execute(select(Corporate).where(Corporate.id == candidate.corporate_id))
    ).scalar_one_or_none()

    assessments = (
        await db.execute(
            select(Assessment)
            .where(Assessment.package_id == candidate.package_id)
            .order_by(Assessment.position)
        )
    ).scalars().all()

    progress_rows = (
        await db.execute(
            select(CandidateProgress).where(
                CandidateProgress.candidate_id == candidate_id
            )
        )
    ).scalars().all()
    progress_by_id = {p.assessment_id: p for p in progress_rows}

    response_rows = (
        await db.execute(
            select(CandidateResponse).where(
                CandidateResponse.candidate_id == candidate_id
            )
        )
    ).scalars().all()
    responses_by_assessment: dict[UUID, dict[str, object]] = {}
    for row in response_rows:
        bucket = responses_by_assessment.setdefault(row.assessment_id, {})
        bucket[str(row.question_id)] = row.response

    if TechnicalEvalService.has_missing_open_evals(
        list(assessments), responses_by_assessment
    ):
        try:
            await TechnicalEvalService.evaluate_candidate(
                db,
                candidate=candidate,
                assessments=list(assessments),
                progress_rows=list(progress_rows),
            )
            response_rows = (
                await db.execute(
                    select(CandidateResponse).where(
                        CandidateResponse.candidate_id == candidate_id
                    )
                )
            ).scalars().all()
            responses_by_assessment = {}
            for row in response_rows:
                bucket = responses_by_assessment.setdefault(row.assessment_id, {})
                bucket[str(row.question_id)] = row.response
        except Exception:
            logger.exception(
                "report_data_technical_eval_backfill_failed candidate_id=%s",
                candidate_id,
            )

    eval_row = (
        await db.execute(
            select(CandidateEvaluation).where(
                CandidateEvaluation.candidate_id == candidate_id
            )
        )
    ).scalar_one_or_none()
    eval_payload = eval_row.payload if evaluation_is_ok(eval_row) else None
    jd_eval_status = "ok" if eval_payload is not None else "pending"
    if eval_payload is None:
        try:
            jd_eval, jd_status = await JdScoringService.get_or_evaluate(
                db,
                candidate=candidate,
                package=package,
                assessments=list(assessments),
                progresses=list(progress_rows),
                responses=list(response_rows),
            )
            if jd_eval is not None:
                eval_payload = jd_eval.model_dump()
                jd_eval_status = "ok"
            else:
                jd_eval_status = jd_status
        except Exception:
            logger.exception(
                "report_data_jd_eval_backfill_failed candidate_id=%s", candidate_id
            )
            jd_eval_status = "failed"
    notes_by_title = _notes_by_assessment_title(eval_payload)
    executive = _executive_fields(eval_payload)
    ai_summary = executive["ai_summary"]

    catalog_ids = {a.global_module_id for a in assessments if a.global_module_id}
    catalog_categories: dict[UUID, str | None] = {}
    if catalog_ids:
        catalog_categories = {
            row.id: row.assessment_category
            for row in (
                await db.execute(
                    select(GlobalModule.id, GlobalModule.assessment_category).where(
                        GlobalModule.id.in_(catalog_ids)
                    )
                )
            ).all()
        }

    outcomes: list[ModuleOutcome] = []
    modules: list[TechnicalReportModule] = []
    custom_questions: list[TechnicalReportCustomQuestion] = []
    scores: list[float] = []
    mcq_scores: list[float] = []
    completed_at = None

    for assessment in assessments:
        kind = (assessment.module_kind or TECHNICAL).strip().lower()
        prog = progress_by_id.get(assessment.id)
        if prog and str(prog.status or "").upper() == COMPLETED_STATUS:
            outcomes.append(
                ModuleOutcome(
                    id=assessment.id,
                    title=assessment.title,
                    category=resolve_category(
                        kind,
                        catalog_categories.get(assessment.global_module_id)
                        if assessment.global_module_id
                        else None,
                        assessment.questions,
                    ),
                    score=module_percentage(prog.score, prog.facet_scores),
                    completed_at=prog.completed_at,
                )
            )
            if completed_at is None or (
                prog.completed_at and prog.completed_at > completed_at
            ):
                completed_at = prog.completed_at
        if kind == PSYCHOMETRIC:
            continue

        score = float(prog.score) if prog and prog.score is not None else None
        if score is not None:
            scores.append(score)

        modules.append(
            TechnicalReportModule(
                id=assessment.id,
                title=assessment.title,
                score=score,
                status=prog.status if prog else "NOT_STARTED",
                completed_at=prog.completed_at if prog else None,
            )
        )

        assessment_notes = notes_by_title.get(assessment.title)
        resp_map = responses_by_assessment.get(assessment.id, {})
        for raw in assessment.questions or []:
            if not isinstance(raw, dict):
                continue
            cleaned = _strip_answer_keys(raw)
            qid = str(cleaned.get("id") or "")
            if not qid:
                continue
            # Drop psychometric-ish fields that may leak via mixed JSONB.
            for key in (
                "trait",
                "trait_key",
                "band",
                "bands",
                "psychometric",
                "likert_band",
                "weight",
            ):
                cleaned.pop(key, None)

            resp_raw = resp_map.get(qid)
            qtype = _question_type(cleaned)
            item_score = _score_item(raw, resp_raw)
            if qtype == "mcq" and item_score is not None:
                mcq_scores.append(item_score)
            # Prefer response-embedded feedback; fall back to Gemini per-assessment notes.
            ai_evaluation = _ai_feedback_from_response(resp_raw) or assessment_notes
            custom_questions.append(
                TechnicalReportCustomQuestion(
                    id=qid,
                    prompt=_question_prompt(cleaned) or _question_prompt(raw),
                    question_type=qtype,
                    score=item_score,
                    response_summary=_response_summary(resp_raw),
                    evaluated_competency=(
                        str(cleaned.get("evaluated_competency") or "").strip() or None
                    ),
                    ai_evaluation=ai_evaluation,
                    ai_eval_status=_ai_eval_status_from_response(resp_raw),
                    scorecard=_scorecard_from_response(resp_raw),
                )
            )

    overall = round(sum(scores) / len(scores), 1) if scores else None
    mcq_score = round(sum(mcq_scores) / len(mcq_scores), 1) if mcq_scores else None
    logo_url = _safe_logo_url(getattr(corporate, "logo_url", None) if corporate else None)

    return TechnicalReportData(
        candidate_id=candidate.id,
        company_name=corporate.name if corporate else "",
        candidate_name=candidate.full_name,
        candidate_email=candidate.email,
        target_role=package.target_role if package else None,
        completed_at=completed_at,
        overall_technical_score=overall,
        company_logo_url=logo_url,
        overall_fit=executive["overall_fit"],
        recommendation_key=executive["recommendation_key"],
        recommendation_label=executive["recommendation_label"],
        mcq_score=mcq_score,
        strengths=executive["strengths"],
        risks=executive["risks"],
        competencies=executive["competencies"],
        ai_summary=ai_summary,
        jd_eval_status=jd_eval_status,
        modules=modules,
        custom_questions=custom_questions,
        completed_assessments=build_completed_assessments(outcomes),
        competency_groups=build_competency_groups(candidate.full_name, outcomes),
    )
