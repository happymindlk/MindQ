"""Pydantic contracts for the Master Assessment Library."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.schemas.client_package import CustomQuestionIn
from app.schemas.package_builder import QuestionType
from app.schemas.question_payload import QuestionPayload

AssessmentCategory = Literal["behavioral", "cognitive", "personality"]
ModuleStatus = Literal["draft", "published"]
TimerMode = Literal["strict", "flexible"]

MAX_DURATION_SECONDS = 8 * 60 * 60


class TemplateCreate(BaseModel):
    """Create a master-library template (global_modules row)."""

    model_config = ConfigDict(extra="ignore")

    title: str = Field(min_length=1, max_length=255)
    category: Literal["technical", "psychometric"] = "technical"
    assessment_category: AssessmentCategory | None = None
    description: str | None = None
    time_limit_minutes: int | None = Field(default=None, ge=1, le=480)
    duration_seconds: int | None = Field(default=None, ge=0, le=MAX_DURATION_SECONDS)
    timer_mode: TimerMode = "flexible"
    shuffle_questions: bool = False
    slug: str | None = Field(default=None, max_length=128)

    @field_validator("slug", mode="before")
    @classmethod
    def _blank_slug(cls, value: object) -> object:
        if value == "":
            return None
        return value


class TemplateUpdate(BaseModel):
    """Partial update for template metadata."""

    model_config = ConfigDict(extra="ignore")

    title: str | None = Field(default=None, min_length=1, max_length=255)
    category: Literal["technical", "psychometric"] | None = None
    assessment_category: AssessmentCategory | None = None
    description: str | None = None
    time_limit_minutes: int | None = Field(default=None, ge=1, le=480)
    duration_seconds: int | None = Field(default=None, ge=0, le=MAX_DURATION_SECONDS)
    timer_mode: TimerMode | None = None
    shuffle_questions: bool | None = None
    is_active: bool | None = None
    position: int | None = None

    def touches_runner_config(self) -> bool:
        """Whether this update changes fields that are frozen once published.

        Returns:
            True when timing/shuffle fields are present in the payload.
        """
        return any(
            value is not None
            for value in (
                self.time_limit_minutes,
                self.duration_seconds,
                self.timer_mode,
                self.shuffle_questions,
            )
        )


class TemplateQuestionCreate(BaseModel):
    """Insert a question into the master library for a template.

    When ``payload`` is supplied it is authoritative (dynamic builder path);
    the flat legacy fields are ignored.
    """

    model_config = ConfigDict(extra="ignore")

    question_text: str = Field(default="", max_length=8000)
    evaluation_rubric: str = ""
    question_type: QuestionType = QuestionType.mcq
    options: list[str] = Field(default_factory=list)
    evaluated_competency: str = "Technical"
    weight: int = Field(ge=1, le=5, default=3)
    likert_label_1: str | None = None
    likert_label_5: str | None = None
    # Alias fields accepted from CustomQuestionIn-shaped clients.
    prompt: str | None = None
    correct_answer_or_rubric: str | None = None
    payload: QuestionPayload | None = None

    @model_validator(mode="after")
    def _has_prompt(self) -> TemplateQuestionCreate:
        if self.payload is None and not (self.question_text or self.prompt or "").strip():
            raise ValueError("question_text or payload is required")
        return self


class TemplateQuestionUpdate(BaseModel):
    """Partial update for a master question."""

    model_config = ConfigDict(extra="ignore")

    question_text: str | None = Field(default=None, min_length=1, max_length=8000)
    evaluation_rubric: str | None = None
    question_type: QuestionType | None = None
    options: list[str] | None = None
    evaluated_competency: str | None = None
    weight: int | None = Field(default=None, ge=1, le=5)
    likert_label_1: str | None = None
    likert_label_5: str | None = None
    is_active: bool | None = None
    position: int | None = None
    payload: QuestionPayload | None = None


class TemplateQuestionOut(BaseModel):
    """Master question as returned to ops UI."""

    id: UUID
    template_id: UUID
    question_text: str
    evaluation_rubric: str = ""
    question_type: str = "mcq"
    options: list[str] = Field(default_factory=list)
    evaluated_competency: str = "Technical"
    weight: int = 3
    likert_label_1: str | None = None
    likert_label_5: str | None = None
    question_payload: dict[str, Any] = Field(default_factory=dict)
    builder_payload: dict[str, Any] | None = None
    is_active: bool = True
    position: int = 0
    created_at: datetime | None = None
    updated_at: datetime | None = None


class TemplateSummary(BaseModel):
    """Library list row."""

    id: UUID
    slug: str
    title: str
    description: str | None = None
    category: Literal["technical", "psychometric"]
    module_kind: Literal["technical", "psychometric"]
    assessment_category: AssessmentCategory | None = None
    time_limit_minutes: int | None = None
    duration_seconds: int | None = None
    timer_mode: TimerMode = "flexible"
    shuffle_questions: bool = False
    status: ModuleStatus = "draft"
    version: int = 1
    lineage_id: UUID | None = None
    parent_module_id: UUID | None = None
    published_at: datetime | None = None
    is_locked: bool = False
    linked_package_count: int = 0
    question_count: int = 0
    facet_count: int = 0
    position: int = 0
    is_active: bool = True
    created_at: datetime | None = None
    updated_at: datetime | None = None


class TemplateDetail(TemplateSummary):
    """Template with nested active questions."""

    questions: list[TemplateQuestionOut] = Field(default_factory=list)


class AddTemplateRequest(BaseModel):
    """Attach a master template to a package draft (eager snapshot)."""

    template_id: UUID


class AddTemplateResponse(BaseModel):
    """Result of forking a template into a package cart row."""

    package_id: UUID
    template_id: UUID
    question_count: int
    questions: list[dict[str, Any]] = Field(default_factory=list)
    created: bool = True


# Re-export for sync-question body typing clarity.
SyncQuestionRequest = CustomQuestionIn
