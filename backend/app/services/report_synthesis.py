"""MindQ Report scoring: module outcomes, category averages, breakdown merge.

Everything numeric in the report is computed here, deterministically. Gemini
only contributes prose (see ``app.schemas.jd_evaluation.ReportNarrative``),
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

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.assessment import Assessment
from app.models.candidate_progress import CandidateProgress
from app.models.candidate_response import CandidateResponse
from app.models.global_module import GlobalModule
from app.schemas.jd_evaluation import ReportNarrative
from app.schemas.mindq_report import (
    AssessmentBreakdownItem,
    CategorySummaryItem,
    ReportCategory,
    ReportSubscaleNote,
)
from app.services.candidate_service import COMPLETED_STATUS
from app.services.instrument_results import (
    SCORING_VERSION,
    big_five_subscales,
    build_score_details,
    module_bar_percentage,
    position_band,
)
from app.services.profiles import DerivedProfile
from app.services.scoring import (
    ScoreResult,
    _extract_answer,
    _normalize_answer_set,
    likert_scale_max_from_questions,
    likert_scale_min_from_questions,
    score_assessment_detailed,
)

TIMED_OUT_STATUS = "TIMED_OUT"
TIMED_OUT_BAND = "Timed Out / Incomplete"
TIMED_OUT_NOTE = (
    "Candidate ran out of time before completing all items. "
    "Displayed score reflects attempted responses only."
)

# Internal score_details instrument → Gemini v5 instrument key.
_INSTRUMENT_PROMPT_KEYS: dict[str, str] = {
    "cognicheck": "cognicheck",
    "crt": "crt",
    "big_five": "mini_ipip",
    "hexaco": "hexaco_hh",
    "ipc": "ipip_ipc",
    "initiative": "personal_initiative",
    "sjt": "sjt",
    "mcq": "cognicheck",
    "ability": "ability",
    "likert": "likert",
}

_TIMING_KEYS = frozenset(
    {
        "server_duration_seconds",
        "client_duration_seconds",
        "elapsed",
        "elapsed_seconds",
        "overtime",
        "duration",
        "duration_seconds",
        "time_taken",
        "time_ms",
        "response_time",
        "response_time_ms",
    }
)

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
    """One package assessment resolved for reporting.

    Attributes:
        key: Stable prompt key (``A1``, ``A2``…) used to merge Gemini prose.
        id: Assessment id.
        title: Assessment title shown to HR.
        category: Resolved competency category.
        score: Percentage (0–100), or None when masked / ungradable.
        completed_at: Completion timestamp.
        status: Progress status (``COMPLETED``, ``TIMED_OUT``, ``PENDING``, …).
        scores_released: False until every package assessment is COMPLETED.
        timed_out: True when the attempt finalized after the timer expired.
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
    facet_means: dict[str, Any] | None = None
    interpersonal_profile: dict[str, Any] | None = None
    status: str = COMPLETED_STATUS
    scores_released: bool = True
    timed_out: bool = False


def map_instrument_for_prompt(instrument: str | None, category: CategoryKey) -> str | None:
    """Map internal instrument IDs to the Gemini v5 keys.

    Args:
        instrument: Value from ``score_details.instrument``.
        category: Resolved competency category.

    Returns:
        Prompt-facing instrument key, or None when unknown.
    """
    if not instrument:
        return "cognicheck" if category == "cognitive" else None
    key = _INSTRUMENT_PROMPT_KEYS.get(instrument, instrument)
    if key == "ability" and category == "cognitive":
        return "cognicheck"
    return key


def _facet_means_payload(facet_scores: Any) -> dict[str, Any] | None:
    if not isinstance(facet_scores, Mapping) or not facet_scores:
        return None
    return {
        str(name): (
            {"mean": value.get("mean"), "n": value.get("n")}
            if isinstance(value, Mapping)
            else value
        )
        for name, value in facet_scores.items()
    }


def _interpersonal_profile_payload(progress: CandidateProgress | None) -> dict[str, Any] | None:
    """Return the LLM-facing interpersonal profile when the resolver completed."""
    raw = getattr(progress, "derived_profile", None) if progress is not None else None
    if not raw:
        return None
    try:
        profile = DerivedProfile.model_validate(raw)
    except ValidationError:
        return None
    if profile.status != "complete":
        return None
    return {"resolver": profile.resolver, "version": profile.version, **profile.data}


def _strip_timing(payload: Mapping[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(payload, Mapping):
        return None
    return {k: v for k, v in payload.items() if k not in _TIMING_KEYS}


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
    score: float | int | None,
    facet_scores: Mapping[str, Any] | None,
    questions: Sequence[Any] | None = None,
) -> float | None:
    """Return a 0–100 score for a completed module.

    Likert-only modules have no right/wrong score, so their n-weighted facet
    means are mapped linearly from the item scale (1–5 default, 1–7 for PI)
    onto 0–100.

    Args:
        score: ``candidate_progress.score`` or None.
        facet_scores: ``{facet: {"mean": float, "n": int}}`` from Likert items.
        questions: Optional bank used to detect a 7-point scale.

    Returns:
        Percentage rounded to one decimal, or None when nothing is scorable.
    """
    if score is not None:
        return round(float(score), 1)
    if not isinstance(facet_scores, Mapping):
        return None
    weighted = 0.0
    total_n = 0
    observed_max = LIKERT_MAX
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
        if float(mean) > observed_max:
            observed_max = 7.0 if float(mean) <= 7 else float(mean)
    if total_n == 0:
        return None
    scale_max = float(likert_scale_max_from_questions(questions)) if questions else observed_max
    scale_min = float(likert_scale_min_from_questions(questions)) if questions else LIKERT_MIN
    mean_rating = min(scale_max, max(scale_min, weighted / total_n))
    span = scale_max - scale_min
    if span <= 0:
        return None
    return round((mean_rating - scale_min) / span * 100, 1)


def _as_float(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float, Decimal)):
        return float(value)
    return None


def _score_details_need_refresh(
    details: Any,
    facet_scores: Any,
) -> bool:
    """Return True when stored ``score_details`` must be recomputed for the report.

    Args:
        details: Persisted ``candidate_progress.score_details``.
        facet_scores: Persisted ``candidate_progress.facet_scores``.

    Returns:
        True when the version is stale, subscales use legacy Emotional-stability
        labels, or Big Five facets are present but Extraversion is missing.
    """
    if not isinstance(details, dict) or details.get("scoring_version") != SCORING_VERSION:
        return True
    names = {
        str(row.get("name") or "")
        for row in (details.get("subscales") or [])
        if isinstance(row, dict)
    }
    if "Emotional stability" in names:
        return True
    if isinstance(facet_scores, Mapping) and facet_scores:
        expected = big_five_subscales(facet_scores)
        if expected and len(names) < len(expected):
            return True
        if expected and any(row["name"] not in names for row in expected):
            return True
    return False


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


def _progress_status(prog: CandidateProgress | None) -> str:
    if prog is None:
        return "PENDING"
    status = str(prog.status or "").strip().upper() or "PENDING"
    if status == "NOT_STARTED":
        return "PENDING"
    return status


def _is_attempt_finalized(status: str) -> bool:
    """Whether a progress status counts as a finished attempt for score release."""
    return status in {COMPLETED_STATUS, TIMED_OUT_STATUS}


def _module_timed_out(prog: CandidateProgress | None, completeness: Mapping[str, Any] | None) -> bool:
    """Detect timer expiry / partial submission for report rendering.

    Args:
        prog: Progress row (``overtime`` is set on expired submits).
        completeness: Score-details completeness payload when available.

    Returns:
        True when the attempt should render as timed out / incomplete.
    """
    if prog is None:
        return False
    if bool(getattr(prog, "overtime", False)):
        return True
    status = _progress_status(prog)
    if status == TIMED_OUT_STATUS:
        return True
    if not isinstance(completeness, Mapping):
        return False
    # Expired submits always set overtime; treat sparse incomplete finals the
    # same when the stored status already says timed out above.
    return False


def package_scores_released(
    assessments: Sequence[Assessment],
    progresses: Iterable[CandidateProgress],
) -> bool:
    """True only when every package assessment is marked COMPLETED.

    Timed-out finals still store ``COMPLETED`` on the progress row (with
    ``overtime=True``); both count as finalized for score release.

    Args:
        assessments: Package assessments.
        progresses: Candidate progress rows.

    Returns:
        Whether HR/admin numerical scores may be released.
    """
    if not assessments:
        return False
    progress_by_id = {p.assessment_id: p for p in progresses}
    return all(
        _is_attempt_finalized(_progress_status(progress_by_id.get(assessment.id)))
        for assessment in assessments
    )


def build_module_outcomes(
    assessments: Sequence[Assessment],
    progresses: Iterable[CandidateProgress],
    responses: Iterable[CandidateResponse],
    catalog_categories: Mapping[UUID, str | None],
) -> list[ModuleOutcome]:
    """Resolve package assessments into report outcomes.

    Numerical scores, subscales, and bands are released only when every
    assessment in the package is ``COMPLETED``. Until then, modules are still
    listed with status indicators but score fields are masked as ``null``.

    Args:
        assessments: Package assessments in display order.
        progresses: Candidate progress rows.
        responses: Candidate response rows.
        catalog_categories: Output of ``load_catalog_categories``.

    Returns:
        Outcomes in assessment order, keyed ``A1``…``An``.
    """
    progress_rows = list(progresses)
    progress_by_id = {p.assessment_id: p for p in progress_rows}
    responses_by_assessment: dict[UUID, dict[str, Any]] = {}
    for row in responses:
        responses_by_assessment.setdefault(row.assessment_id, {})[str(row.question_id)] = row.response

    released = package_scores_released(assessments, progress_rows)
    outcomes: list[ModuleOutcome] = []
    for assessment in assessments:
        prog = progress_by_id.get(assessment.id)
        status = _progress_status(prog)
        category = resolve_category(
            assessment.module_kind,
            catalog_categories.get(assessment.global_module_id)
            if assessment.global_module_id
            else None,
            assessment.questions,
        )
        if not released or not _is_attempt_finalized(status) or prog is None:
            outcomes.append(
                ModuleOutcome(
                    key=f"A{len(outcomes) + 1}",
                    id=assessment.id,
                    title=assessment.title,
                    category=category,
                    score=None,
                    completed_at=getattr(prog, "completed_at", None) if prog is not None else None,
                    status=status,
                    scores_released=False,
                    timed_out=_module_timed_out(prog, None),
                )
            )
            continue

        details = getattr(prog, "score_details", None)
        if _score_details_need_refresh(details, getattr(prog, "facet_scores", None)):
            details = _live_score_details(assessment, prog, responses_by_assessment.get(assessment.id, {}))
        score = module_bar_percentage(details, _as_float(prog.score))
        if score is None and category == "technical":
            score = _item_average(
                assessment.questions, responses_by_assessment.get(assessment.id, {})
            )
        details = details or {}
        instrument = details.get("instrument")
        subscales = tuple(details.get("subscales") or ())
        completeness = _strip_timing(details.get("completeness"))
        timed_out = _module_timed_out(prog, completeness)
        # CogniCheck: total only — never send logic-area subscales to Gemini.
        if map_instrument_for_prompt(instrument, category) == "cognicheck":
            subscales = ()
        display_score = details.get("display_score")
        band = details.get("band")
        band_label = details.get("band_label")
        score_kind = details.get("score_kind")
        if timed_out:
            # Never drop a timed-out module: keep attempted score, else 0 / Incomplete.
            if (
                score is None
                and not subscales
                and not display_score
                and score_kind not in {"traits", "circumplex", "count", "domain"}
            ):
                score = 0.0
                display_score = "Incomplete"
            band = "timed_out"
            band_label = TIMED_OUT_BAND
        report_status = TIMED_OUT_STATUS if timed_out else status
        outcomes.append(
            ModuleOutcome(
                key=f"A{len(outcomes) + 1}",
                id=assessment.id,
                title=assessment.title,
                category=category,
                score=score,
                completed_at=prog.completed_at,
                score_kind=score_kind,
                display_score=display_score,
                band=band,
                band_label=band_label,
                subscales=subscales,
                instrument=instrument,
                completeness=completeness,
                facet_means=_facet_means_payload(getattr(prog, "facet_scores", None)),
                interpersonal_profile=_interpersonal_profile_payload(prog),
                status=report_status,
                scores_released=True,
                timed_out=timed_out,
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
        One sentence, or empty string while package scores are withheld.
    """
    if not outcome.scores_released:
        return ""
    first = _first_name(candidate_name)
    if outcome.timed_out:
        answered = None
        total = None
        if isinstance(outcome.completeness, Mapping):
            answered = outcome.completeness.get("items_answered")
            total = outcome.completeness.get("items_total")
        if isinstance(answered, int) and isinstance(total, int) and total > 0:
            return (
                f"{first} timed out on {outcome.title} after answering "
                f"{answered} of {total} items; the score reflects attempted responses only."
            )
        return (
            f"{first} timed out on {outcome.title} before completing all items; "
            "the displayed score reflects attempted responses only."
        )
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
    synthesis: ReportNarrative | None,
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
    out: dict[UUID, str] = {}
    for o in outcomes:
        if not _has_breakdown_row(o):
            continue
        if not o.scores_released:
            out[o.id] = ""
            continue
        out[o.id] = sentences.get(o.key) or fallback_performance_summary(candidate_name, o)
    return out


def _has_breakdown_row(outcome: ModuleOutcome) -> bool:
    if not outcome.scores_released:
        return True
    # Timed-out modules always render so the header count matches the cards.
    if outcome.timed_out or outcome.status == TIMED_OUT_STATUS:
        return True
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
    synthesis: ReportNarrative | None,
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
    if outcome_list and not all(o.scores_released for o in outcome_list):
        return []
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
    outcomes: Iterable[ModuleOutcome],
    summaries: Mapping[UUID, str],
    synthesis: ReportNarrative | None = None,
) -> list[AssessmentBreakdownItem]:
    """Merge sentences onto server-computed scores.

    When package scores are withheld, rows still appear with status and null
    numerical fields. Released packages omit modules with nothing to report.

    Args:
        outcomes: Module outcomes (possibly score-masked).
        summaries: Output of ``performance_summaries``.
        synthesis: Optional Gemini narrative for role_relevance / subscale notes.

    Returns:
        Breakdown rows in category order, then assessment order.
    """
    narratives = synthesis.narratives_by_key() if synthesis else {}
    scored = [o for o in outcomes if _has_breakdown_row(o) and o.id in summaries]
    scored.sort(key=lambda o: CATEGORY_ORDER.index(o.category))
    rows: list[AssessmentBreakdownItem] = []
    for o in scored:
        narrative = narratives.get(o.key)
        notes = [
            ReportSubscaleNote(subscale_key=n.subscale_key, note=n.note)
            for n in (narrative.subscale_notes if narrative else [])
        ]
        timed_out = o.timed_out or o.status == TIMED_OUT_STATUS
        band = (o.band_label or o.band) if o.scores_released else None
        if o.scores_released and timed_out:
            band = TIMED_OUT_BAND
        rows.append(
            AssessmentBreakdownItem(
                category=CATEGORY_LABELS[o.category],
                assessment_name=o.title,
                score=(
                    max(0.0, min(100.0, o.score))
                    if o.scores_released and o.score is not None
                    else None
                ),
                display_score=o.display_score if o.scores_released else None,
                band=band,
                score_kind=o.score_kind if o.scores_released else None,
                subscales=list(o.subscales) if o.scores_released else [],
                performance_summary=summaries[o.id] if o.scores_released else None,
                role_relevance=(
                    narrative.role_relevance if o.scores_released and narrative else None
                ),
                subscale_notes=notes if o.scores_released else [],
                status=TIMED_OUT_STATUS if timed_out else o.status,
                scores_released=o.scores_released,
                timed_out=timed_out,
                status_note=TIMED_OUT_NOTE if timed_out and o.scores_released else None,
            )
        )
    return rows


def prompt_assessments(outcomes: Iterable[ModuleOutcome]) -> list[dict[str, Any]]:
    """Score table handed to Gemini (only scored, completed assessments).

    CogniCheck rows carry the total only (empty subscales). Timing fields are
    never included. Instrument IDs are mapped to the v5 prompt vocabulary.

    Args:
        outcomes: Completed module outcomes.

    Returns:
        ``[{assessment_key, assessment_name, category, score, …}]``.
    """
    rows: list[dict[str, Any]] = []
    for o in outcomes:
        if not (o.scores_released and _has_breakdown_row(o)):
            continue
        instrument = map_instrument_for_prompt(o.instrument, o.category)
        subscales = list(o.subscales)
        if instrument == "cognicheck":
            subscales = []
        row: dict[str, Any] = {
            "assessment_key": o.key,
            "assessment_name": o.title,
            "category": CATEGORY_LABELS[o.category],
            "score": o.score,
            "score_kind": o.score_kind,
            "display_score": o.display_score,
            "band": o.band_label or o.band,
            "subscales": subscales,
            "instrument": instrument,
            "completeness": _strip_timing(o.completeness),
        }
        if o.facet_means:
            row["facet_means"] = o.facet_means
        if o.interpersonal_profile:
            row["interpersonal_profile"] = o.interpersonal_profile
        # Defence in depth: drop any accidental timing keys.
        rows.append({k: v for k, v in row.items() if k not in _TIMING_KEYS})
    return rows


def outcomes_fingerprint(outcomes: Iterable[ModuleOutcome]) -> str:
    """Stable digest of the scores a synthesis was written against.

    Args:
        outcomes: Completed module outcomes.

    Returns:
        Hex SHA-256; changes whenever any completed score or category changes.
    """
    payload = json.dumps(prompt_assessments(outcomes), sort_keys=True, default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
