"""Pydantic contracts for managed-service client packages."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator, model_validator

from app.schemas.package_builder import QuestionType
from app.schemas.question_payload import (
    DEFAULT_CONFIDENTIALITY_NOTICE_TEXT,
    DEFAULT_TOP_DISCLAIMER_TEXT,
)


def _blank_to_none(value: object) -> object:
    """Treat empty strings as omitted optional fields (avoids 422s)."""
    if value == "":
        return None
    return value


def _check_window_order(open_time: datetime | None, close_time: datetime | None) -> None:
    """Reject a close time that does not fall after the open time.

    Args:
        open_time: Package open instant, if set.
        close_time: Package deadline, if set.

    Raises:
        ValueError: ``close_time`` is not strictly after ``open_time``.
    """
    if open_time is not None and close_time is not None and close_time <= open_time:
        raise ValueError("Close time must be after open time")


def _alias_questions_payload(data: Any) -> Any:
    """Accept ``questions`` as custom items (list) or module overrides (dict).

    Args:
        data: Raw request body.

    Returns:
        Body with ``custom_questions`` / ``module_question_overrides`` filled
        when the client sent the shorter ``questions`` key.
    """
    if not isinstance(data, dict):
        return data
    payload = dict(data)
    questions = payload.pop("questions", None)
    if payload.get("custom_questions") is None and isinstance(questions, list):
        payload["custom_questions"] = questions
    if payload.get("module_question_overrides") is None and isinstance(questions, dict):
        payload["module_question_overrides"] = {
            str(key): value if isinstance(value, list) else []
            for key, value in questions.items()
        }
    return payload


class GlobalModuleResponse(BaseModel):
    """Catalog row for the package-builder library."""

    id: UUID
    slug: str
    title: str
    description: str | None = None
    module_kind: Literal["psychometric", "technical"]
    assessment_category: Literal["behavioral", "cognitive", "personality"] | None = None
    time_limit_minutes: int | None = None
    duration_seconds: int | None = None
    timer_mode: Literal["strict", "flexible"] = "flexible"
    shuffle_questions: bool = False
    show_top_disclaimer: bool = False
    top_disclaimer_text: str = DEFAULT_TOP_DISCLAIMER_TEXT
    show_confidentiality_notice: bool = False
    confidentiality_notice_text: str = DEFAULT_CONFIDENTIALITY_NOTICE_TEXT
    status: Literal["draft", "published"] = "published"
    version: int = 1
    lineage_id: UUID | None = None
    question_count: int = 0
    facet_count: int = 0
    position: int = 0
    is_active: bool = True
    # Full question payloads for draft psychometric editability (ops only).
    questions: list[dict[str, Any]] = Field(default_factory=list)


class CustomQuestionIn(BaseModel):
    """Ops-authored technical item on a client package draft."""

    model_config = ConfigDict(extra="ignore")

    id: UUID | None = None
    prompt: str = Field(min_length=1, max_length=8000)
    question_type: QuestionType = QuestionType.mcq
    options: list[str] = Field(default_factory=list)
    correct_answer_or_rubric: str = ""
    evaluated_competency: str = "Technical"
    weight: int = Field(ge=1, le=5, default=3)
    likert_label_1: str | None = None
    likert_label_5: str | None = None


class CustomQuestionOut(CustomQuestionIn):
    """Persisted custom item, including server id and cart position."""

    id: UUID
    position: int = 0


class PackageModuleRef(BaseModel):
    """Selected global module in cart order."""

    global_module_id: UUID
    position: int = 0


class PackagePreviewRequest(BaseModel):
    """Unsaved composer state rendered through the candidate runner (ops only)."""

    model_config = ConfigDict(extra="ignore")

    module_ids: list[UUID] = Field(min_length=1, max_length=30)
    module_question_overrides: dict[str, list[dict[str, Any]]] | None = None


class DraftPackageRequest(BaseModel):
    """Create or replace a draft client package (shopping cart)."""

    model_config = ConfigDict(extra="ignore")

    corporate_id: UUID
    title: str = Field(min_length=1, max_length=255)
    description: str = Field(default="", max_length=50_000)
    target_role: str | None = Field(default=None, max_length=255)
    module_ids: list[UUID] = Field(default_factory=list)
    custom_questions: list[CustomQuestionIn] = Field(default_factory=list)
    module_question_overrides: dict[str, list[dict[str, Any]]] | None = None
    open_time: AwareDatetime | None = None
    close_time: AwareDatetime | None = None

    @model_validator(mode="before")
    @classmethod
    def _accept_questions_alias(cls, data: Any) -> Any:
        return _alias_questions_payload(data)

    @field_validator("title")
    @classmethod
    def _strip_title(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("Title is required")
        return stripped

    @field_validator("target_role", "open_time", "close_time", mode="before")
    @classmethod
    def _optional_blanks(cls, value: object) -> object:
        return _blank_to_none(value)

    @model_validator(mode="after")
    def _window_order(self) -> "DraftPackageRequest":
        _check_window_order(self.open_time, self.close_time)
        return self


class DraftPackageResponse(BaseModel):
    """Draft (or published) package returned to the builder."""

    id: UUID
    corporate_id: UUID
    title: str
    description: str | None = None
    target_role: str | None = None
    status: Literal["draft", "published"]
    is_active: bool
    access_code: str | None = None
    review_token: str | None = None
    review_path: str | None = None
    track_secret: str | None = None
    published_at: datetime | None = None
    open_time: datetime | None = None
    close_time: datetime | None = None
    module_ids: list[UUID] = Field(default_factory=list)
    custom_questions: list[CustomQuestionOut] = Field(default_factory=list)
    module_count: int = 0
    custom_question_count: int = 0


class PublishPackageResponse(DraftPackageResponse):
    """Publish result including sharing links (token paths, not absolute URLs)."""

    access_code: str
    review_token: str
    review_path: str
    candidate_path: str


class ReviewQuestion(BaseModel):
    """Technical item visible on the blind HR review link (keys stripped)."""

    id: str
    prompt: str
    question_type: str
    options: list[str] = Field(default_factory=list)
    evaluated_competency: str | None = None
    likert_label_1: str | None = None
    likert_label_5: str | None = None


class BlindReviewResponse(BaseModel):
    """Public, token-gated payload: technical questions only."""

    package_id: UUID
    title: str
    corporate_name: str | None = None
    status: str
    client_approved: bool = False
    reviewed_at: datetime | None = None
    questions: list[ReviewQuestion] = Field(default_factory=list)


class ClientScorecardAssessment(BaseModel):
    """Sanitized per-assessment row for the HR client portal."""

    id: UUID
    title: str
    module_kind: str
    status: str | None = None
    score: float | None = None
    completed_at: datetime | None = None


class ClientScorecardResponse(BaseModel):
    """Read-only scorecard with psychometric modules removed (no fit or recommendation)."""

    candidate_id: UUID
    full_name: str
    email: str
    package_title: str
    pipeline_status: str
    avg_score: float | None = None
    summary: str | None = None
    assessments: list[ClientScorecardAssessment] = Field(default_factory=list)
    evaluation: dict[str, Any] | None = None


class ClientPipelineRow(BaseModel):
    """One candidate row on the HR client dashboard."""

    id: UUID
    package_id: UUID
    package_title: str
    full_name: str
    email: str
    pipeline_status: str
    completed_assessments: int = 0
    total_assessments: int = 0
    avg_score: float | None = None
    technical_score: float | None = None
    created_at: datetime | None = None
    completed_at: datetime | None = None


ClientCandidateStatus = Literal["invited", "in_progress", "completed"]


class ClientCorporate(BaseModel):
    """Tenant branding shown in the client-portal header."""

    id: UUID
    name: str
    logo_url: str | None = None


class ClientSessionResponse(BaseModel):
    """Client-portal JWT issued after a verified email OTP (legacy exchange shape)."""

    access_token: str
    token_type: Literal["bearer"] = "bearer"
    expires_in: int
    corporate: ClientCorporate


class ClientDashboardCandidate(BaseModel):
    """Read-only candidate row inside a package on the HR dashboard."""

    candidate_id: UUID
    name: str
    email: str
    status: ClientCandidateStatus
    raw_score: float | None = None
    completed_assessments: int = 0
    total_assessments: int = 0
    report_available: bool = False
    report_path: str | None = None


class ClientDashboardPackage(BaseModel):
    """One published package with aggregated candidate metrics."""

    id: UUID
    title: str
    access_code: str
    target_role: str | None = None
    close_time: datetime | None = None
    candidate_path: str
    total_invited: int = 0
    total_completed: int = 0
    candidates: list[ClientDashboardCandidate] = Field(default_factory=list)


class ClientDashboardResponse(BaseModel):
    """Full HR dashboard payload, scoped to the caller's tenant."""

    corporate: ClientCorporate
    packages: list[ClientDashboardPackage] = Field(default_factory=list)


class BlindReviewApproveResponse(BaseModel):
    """Token-gated HR approval acknowledgement."""

    success: bool = True
    message: str = "Assessment approved successfully"


class CorporateListItem(BaseModel):
    """Ops company picker / history tier-1 row."""

    id: UUID
    name: str
    slug: str
    contact_email: str | None = None
    allowed_hr_emails: list[str] = Field(default_factory=list)
    is_active: bool = True
    logo_url: str | None = None
    package_count: int = 0
    candidate_count: int = 0
    created_at: datetime | None = None


def _normalize_optional_email(value: str | None) -> str | None:
    """Lower-case and sanity-check an optional email; blank means unset.

    Args:
        value: Raw email from the request body.

    Returns:
        Normalized email, or None when blank.

    Raises:
        ValueError: The value is not a plausible email address.
    """
    if value is None:
        return None
    stripped = value.strip().lower()
    if not stripped:
        return None
    local, _, domain = stripped.partition("@")
    if not local or "." not in domain or domain.startswith(".") or domain.endswith("."):
        raise ValueError("A valid email address is required")
    return stripped


def _normalize_email_list(value: object) -> list[str]:
    """Normalize an HR whitelist: lower-case, validate, de-duplicate.

    Args:
        value: Raw list from the request body (None means unset).

    Returns:
        Normalized emails in first-seen order.

    Raises:
        ValueError: The value is not a list, or an entry is not a valid email.
    """
    if value is None:
        return []
    if not isinstance(value, (list, tuple)):
        raise ValueError("allowed_hr_emails must be a list of email addresses")
    normalized: list[str] = []
    seen: set[str] = set()
    for entry in value:
        email = _normalize_optional_email(str(entry) if entry is not None else None)
        if email is None:
            raise ValueError("A valid email address is required")
        if email not in seen:
            seen.add(email)
            normalized.append(email)
    return normalized


def _require_company_name(value: str) -> str:
    """Strip a company name and reject whitespace-only input.

    Args:
        value: Raw company name.

    Returns:
        Stripped company name.

    Raises:
        ValueError: The name is blank after stripping.
    """
    stripped = value.strip()
    if not stripped:
        raise ValueError("Company name is required")
    return stripped


class CompanyCreateRequest(BaseModel):
    """Ops payload to onboard a client company."""

    name: str = Field(min_length=1, max_length=255)
    slug: str | None = Field(default=None, max_length=255)
    contact_email: str | None = Field(default=None, max_length=255)
    allowed_hr_emails: list[str] = Field(default_factory=list, max_length=100)

    @field_validator("name")
    @classmethod
    def _strip_name(cls, value: str) -> str:
        return _require_company_name(value)

    @field_validator("slug")
    @classmethod
    def _empty_slug(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        return stripped or None

    @field_validator("contact_email")
    @classmethod
    def _email(cls, value: str | None) -> str | None:
        return _normalize_optional_email(value)

    @field_validator("allowed_hr_emails", mode="before")
    @classmethod
    def _emails(cls, value: object) -> list[str]:
        return _normalize_email_list(value)


class CompanyUpdateRequest(BaseModel):
    """Ops payload to edit a company; omitted fields are left unchanged."""

    name: str | None = Field(default=None, min_length=1, max_length=255)
    contact_email: str | None = Field(default=None, max_length=255)
    allowed_hr_emails: list[str] | None = Field(default=None, max_length=100)

    @field_validator("name")
    @classmethod
    def _strip_name(cls, value: str | None) -> str | None:
        if value is None:
            raise ValueError("Company name cannot be null")
        return _require_company_name(value)

    @field_validator("contact_email")
    @classmethod
    def _email(cls, value: str | None) -> str | None:
        return _normalize_optional_email(value)

    @field_validator("allowed_hr_emails", mode="before")
    @classmethod
    def _emails(cls, value: object) -> list[str] | None:
        if value is None:
            raise ValueError("allowed_hr_emails cannot be null")
        return _normalize_email_list(value)


class CompanyCreateResponse(BaseModel):
    """Corporates row returned after an ops create or update."""

    id: UUID
    name: str
    slug: str
    contact_email: str | None = None
    allowed_hr_emails: list[str] = Field(default_factory=list)
    is_active: bool = True
    logo_url: str | None = None
    created_at: datetime


class CompanyLogoResponse(BaseModel):
    """Public logo URL persisted on the corporates row."""

    logo_url: str


PackageDisplayStatus = Literal["draft", "published", "archived"]


class CorporatePackageItem(BaseModel):
    """One package on the ops corporate history page."""

    id: UUID
    title: str
    target_role: str | None = None
    status: PackageDisplayStatus
    access_code: str
    invited_count: int = 0
    completed_count: int = 0
    published_at: datetime | None = None
    created_at: datetime | None = None
    open_time: datetime | None = None
    close_time: datetime | None = None
    candidate_link: str | None = None
    hr_login_link: str | None = None


class PackageDeleteResponse(BaseModel):
    """Result of ops package delete / soft-archive."""

    id: UUID
    status: Literal["archived", "deleted"]


class SharePackageRequest(BaseModel):
    """Ops payload to email package access; blank recipient falls back to HR contact."""

    recipient_email: str | None = Field(default=None, max_length=255)

    @field_validator("recipient_email")
    @classmethod
    def _email(cls, value: str | None) -> str | None:
        return _normalize_optional_email(value)


class SharePackageResponse(BaseModel):
    """Delivery acknowledgement plus the links that were sent."""

    success: bool = True
    sent_to: str
    candidate_link: str
    access_code: str
    hr_login_link: str


class AdminPackageModule(BaseModel):
    """Joined package_modules row plus global_modules catalog fields."""

    module_id: UUID
    sort_order: int
    slug: str
    title: str
    description: str | None = None
    module_kind: Literal["psychometric", "technical"]
    time_limit_minutes: int | None = None
    duration_seconds: int | None = None
    timer_mode: Literal["strict", "flexible"] = "flexible"
    show_top_disclaimer: bool = False
    top_disclaimer_text: str = DEFAULT_TOP_DISCLAIMER_TEXT
    show_confidentiality_notice: bool = False
    confidentiality_notice_text: str = DEFAULT_CONFIDENTIALITY_NOTICE_TEXT
    version: int = 1
    # Set when a draft cart row was resolved to a newer published version of its lineage.
    upgraded_from_version: int | None = None
    question_count: int = 0
    is_active: bool = True
    # Draft-time editable copy (psychometric overrides); catalog fallback when null.
    questions: list[dict[str, Any]] = Field(default_factory=list)


class AdminPackageDetail(BaseModel):
    """Single-package state for draft rehydration."""

    id: UUID
    corporate_id: UUID
    title: str
    target_role: str | None = None
    status: Literal["draft", "published"]
    review_token: str | None = None
    description: str | None = None
    is_active: bool = False
    access_code: str | None = None
    open_time: datetime | None = None
    close_time: datetime | None = None
    modules: list[AdminPackageModule] = Field(default_factory=list)
    custom_questions: list[CustomQuestionOut] = Field(default_factory=list)


class AdminPackageUpdateRequest(BaseModel):
    """Replace draft package metadata, modules, and custom questions."""

    model_config = ConfigDict(extra="ignore")

    title: str = Field(min_length=1, max_length=255)
    # Role Assessment Brief. None keeps the stored value so older clients cannot wipe it.
    description: str | None = Field(default=None, max_length=50_000)
    target_role: str | None = Field(default=None, max_length=255)
    corporate_id: UUID | None = None
    module_ids: list[UUID] = Field(default_factory=list)
    custom_questions: list[CustomQuestionIn] | None = None
    # Optional per-module question overrides keyed by global_module_id (draft only).
    module_question_overrides: dict[str, list[dict[str, Any]]] | None = None
    open_time: AwareDatetime | None = None
    close_time: AwareDatetime | None = None

    @model_validator(mode="before")
    @classmethod
    def _accept_questions_alias(cls, data: Any) -> Any:
        return _alias_questions_payload(data)

    @field_validator("title")
    @classmethod
    def _strip_title(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("Title is required")
        return stripped

    @field_validator("target_role", "open_time", "close_time", mode="before")
    @classmethod
    def _optional_blanks(cls, value: object) -> object:
        return _blank_to_none(value)

    @model_validator(mode="after")
    def _window_order(self) -> "AdminPackageUpdateRequest":
        _check_window_order(self.open_time, self.close_time)
        return self


class PackageScheduleUpdate(BaseModel):
    """Ops deadline change for a draft or live package (Extend Deadline)."""

    model_config = ConfigDict(extra="forbid")

    close_time: AwareDatetime | None = None

    @field_validator("close_time", mode="before")
    @classmethod
    def _blank(cls, value: object) -> object:
        return _blank_to_none(value)


class PackageScheduleResponse(BaseModel):
    """Package window after a schedule change."""

    id: UUID
    open_time: datetime | None = None
    close_time: datetime | None = None


class PackageUpdate(AdminPackageUpdateRequest):
    """Alias for PUT package payloads (optional ``questions`` / ``target_role``)."""


class HrInviteRequest(BaseModel):
    """Ops payload to provision an HR user for a company."""

    email: str = Field(min_length=3, max_length=255)

    @field_validator("email")
    @classmethod
    def _normalize_email(cls, value: str) -> str:
        stripped = value.strip().lower()
        if "@" not in stripped or "." not in stripped.split("@", 1)[-1]:
            raise ValueError("A valid email address is required")
        return stripped


class HrInviteResponse(BaseModel):
    """Acknowledgement after Auth invite + hr_users upsert."""

    success: bool = True
    message: str = "Access link sent"
    email: str | None = None
