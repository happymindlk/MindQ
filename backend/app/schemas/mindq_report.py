"""HTTP response schema for the MindQ Report (preview, PDF, bulk export)."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field

from app.schemas.jd_evaluation import (
    ALIGNMENT_LABELS,
    Alignment,
    CapabilityKey,
    Confidence,
    Importance,
)

ReportCategory = Literal["Cognitive", "Personality", "Behavioral", "Technical"]
SynthesisStatus = Literal["ok", "failed", "skipped", "pending"]


class SubscaleScore(BaseModel):
    """One trait or facet shown under a module that must not be blended."""

    name: str
    mean: float | None = None
    sum: float | None = None
    position_pct: float | None = None
    band: str | None = None
    band_label: str | None = None


class ReportSubscaleNote(BaseModel):
    """Gemini note for one subscale, exposed on the report breakdown."""

    subscale_key: str
    note: str


class AssessmentBreakdownItem(BaseModel):
    """One package assessment in the competency breakdown.

    Numerical fields stay null until the candidate's entire package is
    ``COMPLETED`` (``scores_released=False``). Timed-out modules still render
    with a ``TIMED_OUT`` status and an explicit incomplete band.
    """

    category: ReportCategory
    assessment_name: str
    score: float | None = Field(default=None, ge=0, le=100)
    display_score: str | None = None
    band: str | None = None
    score_kind: str | None = None
    subscales: list[SubscaleScore] = Field(default_factory=list)
    # Concise sentence on performance; null while scores are withheld.
    performance_summary: str | None = None
    role_relevance: str | None = None
    subscale_notes: list[ReportSubscaleNote] = Field(default_factory=list)
    status: str | None = None
    scores_released: bool = True
    timed_out: bool = False
    # Explains timed-out / partial submissions under the competency card.
    status_note: str | None = None


PsychometricCategory = Literal["Cognitive", "Personality", "Behavioral"]


class CategorySummaryItem(BaseModel):
    """Holistic prose summary for one psychometric pillar (Technical excluded)."""

    category: PsychometricCategory
    summary: str


class RoleAlignmentReportItem(BaseModel):
    """One capability row in the role-alignment table."""

    capability_key: CapabilityKey
    capability_label: str
    importance: Importance
    alignment: Alignment
    alignment_label: str
    confidence: Confidence
    evidence: str


class ReportCustomQuestion(BaseModel):
    """Sanitized technical item evaluation (no answer keys)."""

    id: str
    prompt: str
    question_type: str
    score: float | None = None
    response_summary: str | None = None
    evaluated_competency: str | None = None
    ai_evaluation: str | None = None
    # Discriminator from response JSONB: ``ok`` | ``failed`` (legacy ``unavailable``).
    ai_eval_status: str | None = None
    scorecard: list[str] | None = None


class MindQReport(BaseModel):
    """Core MindQ Report content (synthesis v5 narrative + scored modules).

    ``category_averages`` is always null (Scoring Spec v2 forbids unlike-test
    pillar averages). Clients hide the dashboard cards when this is empty.
    """

    candidate_full_name: str
    candidate_email: str
    target_role: str
    total_assessments_completed: int = Field(ge=0)
    category_averages: dict[ReportCategory, float] | None = None
    headline: str = ""
    key_takeaways: list[str] = Field(default_factory=list)
    executive_summary: str
    role_alignment: list[RoleAlignmentReportItem] = Field(default_factory=list)
    strengths: list[str] = Field(default_factory=list)
    areas_to_explore: list[str] = Field(default_factory=list)
    work_environment_notes: list[str] = Field(default_factory=list)
    interview_focus_areas: list[str] = Field(default_factory=list)
    verify_separately: list[str] = Field(default_factory=list)
    support_suggestions: list[str] = Field(default_factory=list)
    reliability_notes: list[str] = Field(default_factory=list)
    competency_breakdown: list[AssessmentBreakdownItem] = Field(default_factory=list)
    category_summaries: list[CategorySummaryItem] = Field(default_factory=list)


class MindQReportResponse(MindQReport):
    """MindQ Report plus branding and item-level technical detail for rendering."""

    candidate_id: UUID
    company_name: str
    # Absolute https logo only (localhost filtered out for PDF safety).
    company_logo_url: str | None = None
    completed_at: datetime | None = None
    # Lets the UI tell "synthesis failed" apart from "not yet run".
    synthesis_status: SynthesisStatus = "pending"
    custom_questions: list[ReportCustomQuestion] = Field(default_factory=list)


def role_alignment_for_report(items: list[Any] | None) -> list[RoleAlignmentReportItem]:
    """Map Gemini role_alignment rows onto the HTTP report shape.

    Args:
        items: ``ReportNarrative.role_alignment`` rows (or None).

    Returns:
        Rows with display ``alignment_label`` filled from ``ALIGNMENT_LABELS``.
    """
    out: list[RoleAlignmentReportItem] = []
    for item in items or []:
        if hasattr(item, "model_dump"):
            data = item.model_dump()
        elif isinstance(item, dict):
            data = item
        else:
            continue
        alignment = data.get("alignment")
        out.append(
            RoleAlignmentReportItem(
                capability_key=data["capability_key"],
                capability_label=data["capability_label"],
                importance=data["importance"],
                alignment=alignment,
                alignment_label=ALIGNMENT_LABELS.get(alignment, str(alignment or "")),
                confidence=data["confidence"],
                evidence=data["evidence"],
            )
        )
    return out
