"""MindQ Report synthesis: competency grouping, averages, and narratives.

Narratives are rule-based rather than model-generated so that two candidates
with identical scores always receive identical wording — a requirement for a
defensible, auditable selection document.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Iterable, Literal, Mapping, Sequence
from uuid import UUID

from app.schemas.client_package import (
    ReportAssessmentScore,
    ReportCompetencyGroup,
    ReportCompletedAssessment,
)

ReportCategory = Literal["cognitive", "behavioral", "personality", "technical"]
Band = Literal["exceptional", "strong", "moderate", "developing", "emerging"]

CATEGORY_ORDER: tuple[ReportCategory, ...] = (
    "cognitive",
    "behavioral",
    "personality",
    "technical",
)
CATEGORY_LABELS: dict[ReportCategory, str] = {
    "cognitive": "Cognitive",
    "behavioral": "Behavioral",
    "personality": "Personality",
    "technical": "Technical",
}
PSYCHOMETRIC_CATEGORIES = frozenset({"cognitive", "behavioral", "personality"})

LIKERT_MIN = 1.0
LIKERT_MAX = 5.0
NOTABLE_SPREAD = 15.0

BAND_THRESHOLDS: tuple[tuple[float, Band], ...] = (
    (80.0, "exceptional"),
    (65.0, "strong"),
    (50.0, "moderate"),
    (35.0, "developing"),
)

BAND_COPY: dict[ReportCategory, dict[Band, str]] = {
    "cognitive": {
        "exceptional": (
            "This indicates exceptional reasoning ability: {first} processes complex "
            "information quickly, identifies patterns accurately, and is likely to resolve "
            "novel problems with minimal guidance."
        ),
        "strong": (
            "This reflects strong analytical capability; {first} interprets information "
            "accurately and should handle demanding problem-solving tasks with confidence."
        ),
        "moderate": (
            "This reflects solid, functional reasoning; {first} handles routine analytical "
            "tasks reliably but may need additional time or structure on highly complex, "
            "unfamiliar problems."
        ),
        "developing": (
            "This suggests reasoning skills that are still developing; {first} may benefit "
            "from clear procedures and support when facing complex or ambiguous problems."
        ),
        "emerging": (
            "This indicates that complex analytical tasks are currently a challenge; roles "
            "with heavy problem-solving demands may require targeted support and development."
        ),
    },
    "behavioral": {
        "exceptional": (
            "This indicates highly effective workplace judgement: {first} consistently "
            "selects constructive, well-calibrated responses to interpersonal and "
            "situational challenges."
        ),
        "strong": (
            "This reflects sound judgement in workplace situations; {first} generally "
            "chooses effective, professional courses of action."
        ),
        "moderate": (
            "This reflects generally appropriate workplace judgement, with some situations "
            "where alternative responses would have been more effective."
        ),
        "developing": (
            "This suggests situational judgement that is still developing; {first} may "
            "benefit from guidance on prioritisation and handling interpersonal challenges."
        ),
        "emerging": (
            "This indicates that {first}'s preferred responses often diverged from the most "
            "effective approaches; behavioural expectations should be explored further "
            "during interview."
        ),
    },
    "personality": {
        "exceptional": (
            "This indicates a very strong expression of the measured work-related traits, "
            "pointing to a consistent and well-defined behavioural style."
        ),
        "strong": (
            "This reflects a clear tendency toward the measured traits, suggesting a stable "
            "and recognisable working style."
        ),
        "moderate": (
            "This reflects a balanced profile; {first} adapts their style across situations "
            "rather than showing a strong preference."
        ),
        "developing": (
            "This suggests a lower expression of the measured traits; {first} may prefer "
            "working approaches that differ from the profile assessed."
        ),
        "emerging": (
            "This indicates a markedly low expression of the measured traits; fit with roles "
            "that demand these characteristics should be explored during interview."
        ),
    },
    "technical": {
        "exceptional": (
            "This indicates expert-level command of the assessed technical domain; {first} "
            "is likely to contribute independently from the outset."
        ),
        "strong": (
            "This reflects strong technical proficiency; {first} demonstrates a dependable "
            "grasp of the core concepts required for the role."
        ),
        "moderate": (
            "This reflects working technical knowledge with some gaps; {first} should "
            "perform well on familiar tasks with support on advanced topics."
        ),
        "developing": (
            "This suggests technical knowledge that is still developing; structured "
            "onboarding and mentoring would likely be required."
        ),
        "emerging": (
            "This indicates significant gaps in the assessed technical domain relative to "
            "the role's requirements."
        ),
    },
}


@dataclass(frozen=True)
class ModuleOutcome:
    """One completed assessment resolved for report synthesis.

    Attributes:
        id: Assessment id.
        title: Assessment title shown to HR.
        category: Resolved competency category.
        score: Percentage score (0–100), or None when ungradable.
        completed_at: Completion timestamp.
    """

    id: UUID
    title: str
    category: ReportCategory
    score: float | None
    completed_at: datetime | None


def resolve_category(
    module_kind: str | None,
    catalog_category: str | None,
    questions: Sequence[Any] | None,
) -> ReportCategory:
    """Resolve the competency category for an assessment.

    The catalog's ``assessment_category`` wins; legacy psychometric modules
    without one are inferred from their item formats.

    Args:
        module_kind: ``assessments.module_kind`` (``technical`` | ``psychometric``).
        catalog_category: ``global_modules.assessment_category`` when linked.
        questions: Stored question bank for format-based inference.

    Returns:
        One of ``cognitive``, ``behavioral``, ``personality``, ``technical``.
    """
    if (module_kind or "technical").strip().lower() != "psychometric":
        return "technical"
    normalized = (catalog_category or "").strip().lower()
    if normalized in PSYCHOMETRIC_CATEGORIES:
        return normalized  # type: ignore[return-value]
    types = {
        str(q.get("type") or q.get("question_type") or "").strip().lower()
        for q in questions or []
        if isinstance(q, dict)
    }
    if "likert" in types:
        return "personality"
    if "sjt" in types:
        return "behavioral"
    return "cognitive"


def module_percentage(
    score: float | int | None, facet_scores: Mapping[str, Any] | None
) -> float | None:
    """Return a 0–100 score for a completed module.

    Gradable modules use their stored percentage. Likert-only modules have no
    right/wrong score, so their n-weighted facet means are mapped linearly from
    the 1–5 scale onto 0–100.

    Args:
        score: ``candidate_progress.score`` (percentage) or None.
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


def score_band(score: float) -> Band:
    """Map a percentage onto a descriptive band.

    Args:
        score: Percentage in 0–100.

    Returns:
        Band key used to select narrative copy.
    """
    for threshold, band in BAND_THRESHOLDS:
        if score >= threshold:
            return band
    return "emerging"


def _first_name(full_name: str) -> str:
    parts = full_name.strip().split()
    return parts[0] if parts else "The candidate"


def _format_pct(value: float) -> str:
    return f"{value:g}%"


def build_narrative(
    category: ReportCategory,
    candidate_name: str,
    modules: Sequence[ModuleOutcome],
    average: float | None,
) -> str:
    """Compose the descriptive paragraph for one competency group.

    Args:
        category: Competency category being described.
        candidate_name: Candidate full name (first name is used in prose).
        modules: Completed modules in this category.
        average: Group average percentage, or None when nothing is scorable.

    Returns:
        A short, deterministic paragraph explaining the candidate's abilities.
    """
    first = _first_name(candidate_name)
    label = CATEGORY_LABELS[category].lower()
    if average is None:
        return (
            f"{first} completed the {label} assessments, but scores are not yet available "
            "for interpretation."
        )

    scored = [m for m in modules if m.score is not None]
    noun = "assessment" if len(scored) == 1 else "assessments"
    opener = (
        f"{first} achieved an average of {_format_pct(average)} across "
        f"{len(scored)} {label} {noun}."
    )
    body = BAND_COPY[category][score_band(average)].format(first=first)

    closing = ""
    if len(scored) >= 2:
        best = max(scored, key=lambda m: m.score or 0.0)
        worst = min(scored, key=lambda m: m.score or 0.0)
        if (best.score or 0.0) - (worst.score or 0.0) >= NOTABLE_SPREAD:
            closing = (
                f" Performance was strongest in {best.title} ({_format_pct(best.score or 0.0)})"
                f" and comparatively lower in {worst.title} "
                f"({_format_pct(worst.score or 0.0)}), indicating a relative strength in the "
                "former area."
            )
        else:
            closing = " Results were consistent across modules, indicating a stable profile."
    return f"{opener} {body}{closing}"


def build_competency_groups(
    candidate_name: str, modules: Iterable[ModuleOutcome]
) -> list[ReportCompetencyGroup]:
    """Group completed modules by category with averages and narratives.

    Args:
        candidate_name: Candidate full name for narrative copy.
        modules: Completed module outcomes in display order.

    Returns:
        Groups in fixed Cognitive → Behavioral → Personality → Technical order;
        categories with no completed modules are omitted.
    """
    by_category: dict[ReportCategory, list[ModuleOutcome]] = {}
    for module in modules:
        by_category.setdefault(module.category, []).append(module)

    groups: list[ReportCompetencyGroup] = []
    for category in CATEGORY_ORDER:
        members = by_category.get(category)
        if not members:
            continue
        scores = [m.score for m in members if m.score is not None]
        average = round(sum(scores) / len(scores), 1) if scores else None
        groups.append(
            ReportCompetencyGroup(
                key=category,
                label=CATEGORY_LABELS[category],
                average_score=average,
                assessments=[
                    ReportAssessmentScore(id=m.id, title=m.title, score=m.score)
                    for m in members
                ],
                narrative=build_narrative(category, candidate_name, members, average),
            )
        )
    return groups


def build_completed_assessments(
    modules: Iterable[ModuleOutcome],
) -> list[ReportCompletedAssessment]:
    """List completed modules for the report's "Completed Assessments" section.

    Args:
        modules: Completed module outcomes in display order.

    Returns:
        One row per completed module with its category label and completion date.
    """
    return [
        ReportCompletedAssessment(
            id=m.id,
            title=m.title,
            category=m.category,
            category_label=CATEGORY_LABELS[m.category],
            completed_at=m.completed_at,
        )
        for m in modules
    ]
