import uuid
from datetime import datetime
from typing import Annotated, Any, Optional
from pydantic import BaseModel, EmailStr, ConfigDict, Field, StringConstraints, field_validator


# Keep in sync with ``client_package.ANSWER_KEYS`` — candidate portal defense in depth.
_ANSWER_KEY_ALIASES = (
    "correct_answer",
    "correct_answer_or_rubric",
    "benchmark_rubric",
    "answer",
    "scoring_key",
    "is_correct",
    "correct_keys",
    "option_weights",
    "accepted_answers",
    "reverse_scored",
    "sme_rationale",
    "facet",
)


def strip_answer_keys(questions: list[Any] | None) -> list[dict[str, Any]]:
    """Copy stored JSONB questions and drop answer keys before they leave the API.

    Args:
        questions: Raw `assessments.questions` JSONB payload.

    Returns:
        A new list of question dicts with scoring keys removed. The source list
        is never mutated so a later session commit cannot persist a stripped
        question bank.
    """
    sanitized: list[dict[str, Any]] = []
    for raw in questions or []:
        if not isinstance(raw, dict):
            continue
        item = dict(raw)
        for key in _ANSWER_KEY_ALIASES:
            item.pop(key, None)
        sanitized.append(item)
    return sanitized


class CandidateBase(BaseModel):
    full_name: str
    email: EmailStr


class CandidateInviteRequest(BaseModel):
    candidate_email: EmailStr
    package_id: uuid.UUID
    corporate_id: uuid.UUID


class CandidateInviteResponse(BaseModel):
    id: uuid.UUID
    candidate_email: EmailStr
    package_id: uuid.UUID
    access_code: str
    status: str = "pending"


class CandidateLogin(BaseModel):
    """Candidate sign-in payload. Email ownership is proven separately via OTP."""

    first_name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]
    full_name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=255)]
    email: EmailStr
    access_code: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=36)]


class CandidateResponse(CandidateBase):
    id: uuid.UUID
    first_name: Optional[str] = None
    corporate_id: uuid.UUID
    package_id: uuid.UUID
    access_code: str
    logged_in_at: Optional[datetime] = None
    created_at: datetime
    token: Optional[str] = None

    package_title: Optional[str] = None
    status: Optional[str] = None
    progress: Optional[str] = None
    score: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)


class CandidateProgressResponse(BaseModel):
    id: uuid.UUID
    assessment_id: uuid.UUID
    status: str
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    score: Optional[float] = None

    model_config = ConfigDict(from_attributes=True)


class CandidateQuestion(BaseModel):
    """Public question payload. Extra keys (correct_answer, is_correct, …) are dropped."""

    model_config = ConfigDict(extra="ignore")

    id: str
    text: str = ""
    type: str
    options: list[str] = Field(default_factory=list)
    allow_multiple: bool = False
    media_url: Optional[str] = None
    likert_label_1: Optional[str] = None
    likert_label_5: Optional[str] = None
    scale_labels: Optional[list[str]] = None

    @field_validator("id", mode="before")
    @classmethod
    def coerce_id(cls, value: Any) -> str:
        return str(value)

    @field_validator("options", mode="before")
    @classmethod
    def coerce_options(cls, value: Any) -> list:
        return value or []

    @field_validator("allow_multiple", mode="before")
    @classmethod
    def coerce_allow_multiple(cls, value: Any) -> bool:
        return bool(value)


class CandidateTestResponse(BaseModel):
    """GET /candidate/test/{id} — questions are typed so answer keys cannot leak."""

    model_config = ConfigDict(from_attributes=True, extra="ignore")

    id: uuid.UUID
    title: str
    description: Optional[str] = None
    time_limit_minutes: Optional[int] = None
    duration_seconds: Optional[int] = None
    timer_mode: str = "flexible"
    shuffle_questions: bool = False
    started_at: Optional[datetime] = None
    questions: list[CandidateQuestion] = Field(default_factory=list)
    answers: dict[str, Any] = Field(default_factory=dict)
