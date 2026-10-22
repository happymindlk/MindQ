"""HTTP response schema for the MindQ Report (preview, PDF, bulk export)."""
from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field

ReportCategory = Literal["Cognitive", "Personality", "Behavioral", "Technical"]
SynthesisStatus = Literal["ok", "failed", "skipped", "pending"]


class AssessmentBreakdownItem(BaseModel):
    """One completed, scored assessment in the competency breakdown."""

    category: ReportCategory
    assessment_name: str
    score: float = Field(ge=0, le=100)
    # Exactly one concise sentence on how the candidate performed on this test.
    performance_summary: str


PsychometricCategory = Literal["Cognitive", "Personality", "Behavioral"]


class CategorySummaryItem(BaseModel):
    """Holistic prose summary for one psychometric pillar (Technical excluded)."""

    category: PsychometricCategory
    summary: str


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
    """Core MindQ Report content.

    ``category_averages`` only contains categories with at least one completed,
    scored assessment; a category the candidate never took is absent rather
    than reported as 0.
    """

    candidate_full_name: str
    candidate_email: str
    target_role: str
    total_assessments_completed: int = Field(ge=0)
    category_averages: dict[ReportCategory, float] = Field(default_factory=dict)
    executive_summary: str
    strengths: list[str] = Field(default_factory=list)
    risks_and_antipatterns: list[str] = Field(default_factory=list)
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
