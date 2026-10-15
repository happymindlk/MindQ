"""Pydantic contracts for Assessment Package Builder."""
from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field


class QuestionType(str, Enum):
    """Supported item formats in the manual / automated package builder."""

    mcq = "mcq"
    likert = "likert"
    open_ended = "open_ended"


class DifficultyLevel(str, Enum):
    """Target seniority band for the generated package."""

    junior = "junior"
    mid = "mid"
    senior = "senior"
    lead = "lead"


class QuestionItem(BaseModel):
    """A single assessment item in a package blueprint."""

    prompt: str
    question_type: QuestionType
    options: list[str] = Field(default_factory=list)
    correct_answer_or_rubric: str = ""
    evaluated_competency: str = ""
    weight: int = Field(ge=1, le=5, default=3)
    likert_label_1: str = "Strongly Disagree"
    likert_label_5: str = "Strongly Agree"


class AssessmentPackageBlueprint(BaseModel):
    """Structured assessment package ready to persist."""

    title: str
    role: str
    target_seniority: DifficultyLevel
    estimated_duration_minutes: int = Field(ge=5, le=240)
    competencies_targeted: list[str] = Field(default_factory=list)
    questions: list[QuestionItem] = Field(default_factory=list)


class GeneratePackageRequest(BaseModel):
    """HR payload to generate a package blueprint from a job description."""

    role: str = Field(min_length=1, max_length=255)
    job_description: str = Field(min_length=20)
    seniority: DifficultyLevel
    question_count: int = Field(default=10, ge=4, le=20)


class SavePackageRequest(BaseModel):
    """Approved blueprint plus JD text persisted for later JD-fit scoring."""

    blueprint: AssessmentPackageBlueprint
    job_description: str = Field(default="", max_length=50_000)


class SavePackageResponse(BaseModel):
    """Identifiers returned after persisting an approved blueprint."""

    id: str
    access_code: str
    title: str
    assessment_count: int
    question_count: int
