"""MindQ Report scoring: module outcomes, category averages, breakdown merge.

Everything numeric in the report is computed here, deterministically. Gemini
only contributes prose (see ``app.schemas.jd_evaluation.ReportSynthesis``),
which is merged onto these outcomes by a stable ``assessment_key``.
"""
from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any, Literal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.assessment import Assessment
from app.models.candidate_progress import CandidateProgress
from app.models.candidate_response import CandidateResponse
from app.models.global_module import GlobalModule
from app.schemas.jd_evaluation import ReportSynthesis
from app.schemas.mindq_report import (
    AssessmentBreakdownItem,
    CategorySummaryItem,
    ReportCategory,
)
from app.services.candidate_service import COMPLETED_STATUS
from app.services.instrument_results import (
    SCORING_VERSION,
    build_score_details,
    module_bar_percentage,
    position_band,
)
from app.services.scoring import ScoreResult, _extract_answer, _normalize_answer_set, score_assessment_detailed

CategoryKey = Literal["cognitive", "behavioral", "personality", "technical"]
Band = Literal["very_high", "high", "moderate", "low", "very_low"]

CATEGORY_ORDER: tuple[CategoryKey, ...] = ("cognitive", "personality", "behavioral", "technical")
CATEGORY_LABELS: dict[CategoryKey, ReportCategory] = {
    "cognitive": "Cognitive",
    "personality": "Personality",
    "behavioral": "Behavioral",
    "technical": "Technical",
}
PSYCHOMETRIC_CATEGORIES = frozenset({"cognitive", "behavioral", "personality"})

LIKERT_MIN = 1.0
LIKERT_MAX = 5.0

# Used only when Gemini is unavailable or omits an assessment, so every
# breakdown row still carries exactly one sentence.
FALLBACK_SENTENCES: dict[Band, str] = {
    "very_high": "{first} scored {score} on {name}, a very high result on this assessment.",
    "high": "{first} scored {score} on {name}, a high result on this assessment.",
    "moderate": "{first} scored {score} on {name}, a moderate result on this assessment.",
    "low": "{first} scored {score} on {name}, a low result on this assessment.",
    "very_low": "{first} scored {score} on {name}, a very low result on this assessment.",
}


@dataclass(frozen=True)
class ModuleOutcome:
    """One completed assessment resolved for reporting.

    Attributes:
        key: Stable prompt key (``A1``, ``A2``…) used to merge Gemini prose.
        id: Assessment id.
        title: Assessment title shown to HR.
        category: Resolved competency category.
        score: Percentage (0–100), or None when nothing was gradable.
        completed_at: Completion timestamp.
    """

    key: str
    id: UUID
    title: str
    category: CategoryKey
    score: float | None
    completed_at: datetime | None
    score_kind: str | None = None
    display_score: str | None = None
    band: str | None = None
    band_label: str | None = None
    subscales: tuple[dict[str, Any], ...] = ()
    instrument: str | None = None
    completeness: dict[str, Any] | None = None


def question_type(question: Mapping[str, Any]) -> str:
    """Normalize a stored question's type.

    Args:
        question: Stored question dict.

    Returns:
        Lower-cased type, defaulting to ``open_ended``.
    """
    raw = question.get("type") or question.get("question_type") or question.get("builder_type")
    return str(raw or "open_ended").lower()


def _ai_score(response_raw: Any) -> float | None:
    if not isinstance(response_raw, dict):
        return None
    value = response_raw.get("ai_score")
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def score_item(question: Mapping[str, Any], response_raw: Any) -> float | None:
    """Score one technical item: 100/0 for keyed MCQ, graded ``ai_score`` otherwise.

    Args:
        question: Stored question (with answer keys).
        response_raw: ``candidate_responses.response`` JSONB.

    Returns:
        Item percentage, or None when ungraded.
    """
    qtype = question_type(question)
    correct = question.get("correct_answer")
    if correct is None and qtype == "mcq":
        correct = question.get("correct_answer_or_rubric")
    if qtype == "mcq" and correct is not None:
        expected = _normalize_answer_set(correct)
        if expected:
            given = _normalize_answer_set(_extract_answer(response_raw))
            return 100.0 if given == expected else 0.0
    return _ai_score(response_raw)


def resolve_category(
    module_kind: str | None,
    catalog_category: str | None,
    questions: Sequence[Any] | None,
) -> CategoryKey:
    """Resolve the competency category for an assessment.

    The catalog's ``assessment_category`` wins; legacy psychometric modules
    without one are inferred from their item formats.

    Args:
        module_kind: ``assessments.module_kind``.
        catalog_category: ``global_modules.assessment_category`` when linked.
        questions: Stored question bank for format-based inference.

    Returns:
        Internal category key.
    """
    if (module_kind or "technical").strip().lower() != "psychometric":
        return "technical"
    normalized = (catalog_category or "").strip().lower()
    if normalized in PSYCHOMETRIC_CATEGORIES:
        return normalized  # type: ignore[return-value]
    types = {question_type(q) for q in questions or [] if isinstance(q, dict)}
    if "likert" in types:
        return "personality"
    if "sjt" in types:
        return "behavioral"
    return "cognitive"


def module_percentage(
    score: float | int | None, facet_scores: Mapping[str, Any] | None
) -> float | None:
    """Return a 0–100 score for a completed module.

    Likert-only modules have no right/wrong score, so their n-weighted facet
    means are mapped linearly from the 1–5 scale onto 0–100.

    Args:
        score: ``candidate_progress.score`` or None.
        facet_scores: ``{facet: {"mean": float, "n": int}}`` from Likert items.

    Returns:
        Percentage rounded to one decimal, or None when nothing is scorable.
    """
    if score is not None:
        return round(float(score), 1)
    if not isinstance(facet_scores, Mapping):
        return None
    weighted = 0.0
    total_n = 0
    for entry in facet_scores.values():
        if not isinstance(entry, Mapping):
            continue
        mean = entry.get("mean")
        n = entry.get("n", 1)
        if isinstance(mean, bool) or not isinstance(mean, (int, float)):
            continue
        if isinstance(n, bool) or not isinstance(n, int) or n <= 0:
            n = 1
        weighted += float(mean) * n
        total_n += n
    if total_n == 0:
        return None
    mean_rating = min(LIKERT_MAX, max(LIKERT_MIN, weighted / total_n))
    return round((mean_rating - LIKERT_MIN) / (LIKERT_MAX - LIKERT_MIN) * 100, 1)


def _as_float(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float, Decimal)):
        return float(value)
    return None


def _live_score_details(
    assessment: Assessment,
    progress: CandidateProgress,
    response_map: Mapping[str, Any],
) -> dict[str, Any]:
    """Recompute display details for rows scored before scoring v2 persisted them."""
    questions = assessment.questions if isinstance(assessment.questions, list) else []
    rows = [
        type("R", (), {"question_id": qid, "response": raw})()
        for qid, raw in response_map.items()
    ]
    result = (
        score_assessment_detailed(questions, rows)
        if rows or questions
        else ScoreResult(
            score=_as_float(getattr(progress, "score", None)),
            facet_scores=progress.facet_scores or {},
        )
    )
    facets = getattr(progress, "facet_scores", None)
    if isinstance(facets, dict) and facets and not result.facet_scores:
        result.facet_scores = facets
    stored = _as_float(getattr(progress, "score", None))
    if stored is not None:
        result.score = stored
    return build_score_details(
        questions=questions,
        result=result,
        derived_profile=getattr(progress, "derived_profile", None),
        category=resolve_category(
            assessment.module_kind,
            None,
            questions,
        ),
    )


def _item_average(questions: Sequence[Any] | None, responses: Mapping[str, Any]) -> float | None:
    """Mean graded item score for technical modules with only open-ended items."""
    scores = [
        s
        for q in questions or []
        if isinstance(q, dict)
        and (s := score_item(q, responses.get(str(q.get("id") or "")))) is not None
    ]
    return round(sum(scores) / len(scores), 1) if scores else None


async def load_catalog_categories(
    db: AsyncSession, assessments: Iterable[Assessment]
) -> dict[UUID, str | None]:
    """Fetch ``assessment_category`` for linked catalog modules in one query.

    Args:
        db: Async session.
        assessments: Package assessments.

    Returns:
        ``global_modules.id`` → category.
    """
    ids = {a.global_module_id for a in assessments if a.global_module_id}
    if not ids:
        return {}
    rows = await db.execute(
        select(GlobalModule.id, GlobalModule.assessment_category).where(GlobalModule.id.in_(ids))
    )
    return {row.id: row.assessment_category for row in rows.all()}


def build_module_outcomes(
    assessments: Sequence[Assessment],
    progresses: Iterable[CandidateProgress],
    responses: Iterable[CandidateResponse],
    catalog_categories: Mapping[UUID, str | None],
) -> list[ModuleOutcome]:
    """Resolve every *completed* assessment into a scored outcome.

    Args:
        assessments: Package assessments in display order.
        progresses: Candidate progress rows.
        responses: Candidate response rows.
        catalog_categories: Output of ``load_catalog_categories``.

    Returns:
        Outcomes in assessment order, keyed ``A1``…``An``.
    """
    progress_by_id = {p.assessment_id: p for p in progresses}
    responses_by_assessment: dict[UUID, dict[str, Any]] = {}
    for row in responses:
        responses_by_assessment.setdefault(row.assessment_id, {})[str(row.question_id)] = row.response

    outcomes: list[ModuleOutcome] = []
    for assessment in assessments:
        prog = progress_by_id.get(assessment.id)
        if prog is None or str(prog.status or "").upper() != COMPLETED_STATUS:
            continue
        category = resolve_category(
            assessment.module_kind,
            catalog_categories.get(assessment.global_module_id)
            if assessment.global_module_id
            else None,
            assessment.questions,
        )
        details = getattr(prog, "score_details", None)
        if not isinstance(details, dict) or details.get("scoring_version") != SCORING_VERSION:
            details = _live_score_details(assessment, prog, responses_by_assessment.get(assessment.id, {}))
        score = module_bar_percentage(details, _as_float(prog.score))
        if score is None and category == "technical":
            score = _item_average(
                assessment.questions, responses_by_assessment.get(assessment.id, {})
            )
        details = details or {}
        outcomes.append(
            ModuleOutcome(
                key=f"A{len(outcomes) + 1}",
                id=assessment.id,
                title=assessment.title,
                category=category,
                score=score,
                completed_at=prog.completed_at,
                score_kind=details.get("score_kind"),
                display_score=details.get("display_score"),
                band=details.get("band"),
                band_label=details.get("band_label"),
                subscales=tuple(details.get("subscales") or ()),
                instrument=details.get("instrument"),
                completeness=details.get("completeness"),
            )
        )
    return outcomes


def compute_category_averages(outcomes: Iterable[ModuleOutcome]) -> dict[ReportCategory, float] | None:
    """Pillar averages are not part of Scoring Spec v2.

    Unlike instruments must not be averaged. The field remains on the API as
    ``null`` so existing clients hide the dashboard cards.

    Args:
        outcomes: Completed module outcomes (ignored).

    Returns:
        Always ``None``.
    """
    del outcomes
    return None


def score_band(score: float) -> Band:
    """Map a percentage onto a position band (inclusive lower bounds).

    Args:
        score: Percentage in 0–100.

    Returns:
        Band key.
    """
    return position_band(score)  # type: ignore[return-value]


def _first_name(full_name: str) -> str:
    parts = full_name.strip().split()
    return parts[0] if parts else "The candidate"


def fallback_performance_summary(candidate_name: str, outcome: ModuleOutcome) -> str:
    """Deterministic one-sentence summary used when Gemini prose is missing.

    Args:
        candidate_name: Candidate full name.
        outcome: Scored module outcome.

    Returns:
        One sentence.
    """
    first = _first_name(candidate_name)
    if outcome.score_kind == "traits" and outcome.subscales:
        parts = [
            f"{row['name']} {row.get('band_label') or row.get('band')}"
            for row in outcome.subscales
            if isinstance(row, dict)
        ]
        joined = "; ".join(parts) if parts else "recorded trait scores"
        return f"{first} completed {outcome.title} ({joined})."
    if outcome.score_kind == "circumplex":
        style = outcome.display_score or "an undifferentiated style"
        intensity = outcome.band_label or outcome.band or ""
        extra = f", {intensity} intensity" if intensity else ""
        return f"{first}'s result on {outcome.title} is {style}{extra}."
    if outcome.score_kind == "count" and outcome.display_score:
        label = outcome.band_label or outcome.band or ""
        suffix = f", {label.lower()}" if label else ""
        return f"{first} answered {outcome.display_score} items on {outcome.title}{suffix}."
    if outcome.display_score and outcome.score is None:
        label = outcome.band_label or ""
        suffix = f", {label.lower()}" if label else ""
        return f"{first} completed {outcome.title} ({outcome.display_score}{suffix})."
    score = outcome.score or 0.0
    return FALLBACK_SENTENCES[score_band(score)].format(
        first=first, score=f"{score:g}%", name=outcome.title
    )


def performance_summaries(
    candidate_name: str,
    outcomes: Iterable[ModuleOutcome],
    synthesis: ReportSynthesis | None,
) -> dict[UUID, str]:
    """One sentence per scored assessment: Gemini's when present, else fallback.

    Args:
        candidate_name: Candidate full name (fallback copy).
        outcomes: Completed module outcomes.
        synthesis: Gemini synthesis, or None when unavailable.

    Returns:
        Assessment id → sentence, for scored outcomes only.
    """
    sentences = synthesis.summaries_by_key() if synthesis else {}
    return {
        o.id: sentences.get(o.key) or fallback_performance_summary(candidate_name, o)
        for o in outcomes
        if _has_breakdown_row(o)
    }


def _has_breakdown_row(outcome: ModuleOutcome) -> bool:
    return (
        outcome.score is not None
        or bool(outcome.subscales)
        or outcome.score_kind in {"traits", "circumplex", "count", "domain"}
        or bool(outcome.display_score)
    )


def fallback_category_summary(
    candidate_name: str, category: CategoryKey, outcomes: Sequence[ModuleOutcome]
) -> str:
    """Deterministic pillar summary used when Gemini prose is missing.

    Args:
        candidate_name: Candidate full name (fallback copy).
        category: Psychometric pillar key.
        outcomes: Scored outcomes in that pillar.

    Returns:
        Two-sentence summary derived only from server-computed scores.
    """
    label = CATEGORY_LABELS[category]
    rows = [o for o in outcomes if _has_breakdown_row(o)]
    count = len(rows)
    noun = "assessment" if count == 1 else "assessments"
    titles = ", ".join(o.title for o in rows)
    return (
        f"{_first_name(candidate_name)} completed {count} {label} {noun}: {titles}. "
        "Scores for each assessment are reported separately and are not averaged."
    )


def build_category_summaries(
    candidate_name: str,
    outcomes: Iterable[ModuleOutcome],
    synthesis: ReportSynthesis | None,
) -> list[CategorySummaryItem]:
    """Merge pillar prose onto the psychometric pillars actually completed.

    Only Cognitive, Personality, and Behavioral pillars with at least one
    scored outcome are returned, in fixed category order; Technical never
    carries a pillar summary. Gemini prose wins, with a deterministic
    fallback so a pillar never renders blank.

    Args:
        candidate_name: Candidate full name (fallback copy).
        outcomes: Completed module outcomes.
        synthesis: Gemini synthesis, or None when unavailable.

    Returns:
        Pillar summaries in category order.
    """
    outcome_list = list(outcomes)
    prose = synthesis.summaries_by_category() if synthesis else {}
    summaries: list[CategorySummaryItem] = []
    for key in CATEGORY_ORDER:
        if key == "technical":
            continue
        pillar = [o for o in outcome_list if o.category == key and _has_breakdown_row(o)]
        if not pillar:
            continue
        label = CATEGORY_LABELS[key]
        summaries.append(
            CategorySummaryItem(
                category=label,  # type: ignore[arg-type]
                summary=prose.get(label) or fallback_category_summary(candidate_name, key, pillar),
            )
        )
    return summaries


def build_competency_breakdown(
    outcomes: Iterable[ModuleOutcome], summaries: Mapping[UUID, str]
) -> list[AssessmentBreakdownItem]:
    """Merge sentences onto server-computed scores.

    Unscored outcomes are excluded (a breakdown row always has a real score).

    Args:
        outcomes: Completed module outcomes.
        summaries: Output of ``performance_summaries``.

    Returns:
        Breakdown rows in category order, then assessment order.
    """
    scored = [o for o in outcomes if _has_breakdown_row(o) and o.id in summaries]
    scored.sort(key=lambda o: CATEGORY_ORDER.index(o.category))
    return [
        AssessmentBreakdownItem(
            category=CATEGORY_LABELS[o.category],
            assessment_name=o.title,
            score=(
                max(0.0, min(100.0, o.score))
                if o.score is not None
                else None
            ),
            display_score=o.display_score,
            band=o.band_label or o.band,
            score_kind=o.score_kind,
            subscales=list(o.subscales),
            performance_summary=summaries[o.id],
        )
        for o in scored
    ]


def prompt_assessments(outcomes: Iterable[ModuleOutcome]) -> list[dict[str, Any]]:
    """Score table handed to Gemini (only scored, completed assessments).

    Args:
        outcomes: Completed module outcomes.

    Returns:
        ``[{assessment_key, assessment_name, category, score}]``.
    """
    return [
        {
            "assessment_key": o.key,
            "assessment_name": o.title,
            "category": CATEGORY_LABELS[o.category],
            "score": o.score,
            "score_kind": o.score_kind,
            "display_score": o.display_score,
            "band": o.band_label or o.band,
            "subscales": list(o.subscales),
            "instrument": o.instrument,
            "completeness": o.completeness,
        }
        for o in outcomes
        if _has_breakdown_row(o)
    ]


def outcomes_fingerprint(outcomes: Iterable[ModuleOutcome]) -> str:
    """Stable digest of the scores a synthesis was written against.

    Args:
        outcomes: Completed module outcomes.

    Returns:
        Hex SHA-256; changes whenever any completed score or category changes.
    """
    payload = json.dumps(prompt_assessments(outcomes), sort_keys=True, default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
