import uuid
from typing import List, Optional, Any
from datetime import datetime
from pydantic import BaseModel, Field, ConfigDict

from app.schemas.question_payload import (
    CONFIDENTIALITY_TEXT_MAX,
    DEFAULT_CONFIDENTIALITY_NOTICE_TEXT,
    DEFAULT_TOP_DISCLAIMER_TEXT,
    TOP_DISCLAIMER_TEXT_MAX,
)


class AssessmentIn(BaseModel):
    title: str
    description: Optional[str] = None
    time_limit_minutes: Optional[int] = None
    show_top_disclaimer: bool = False
    top_disclaimer_text: str = Field(
        default=DEFAULT_TOP_DISCLAIMER_TEXT, max_length=TOP_DISCLAIMER_TEXT_MAX
    )
    show_confidentiality_notice: bool = False
    confidentiality_notice_text: str = Field(
        default=DEFAULT_CONFIDENTIALITY_NOTICE_TEXT, max_length=CONFIDENTIALITY_TEXT_MAX
    )
    questions: List[Any] = Field(default_factory=list)


class AssessmentResponse(BaseModel):
    id: uuid.UUID
    title: str
    description: Optional[str] = None
    time_limit_minutes: Optional[int] = None
    show_top_disclaimer: bool = False
    top_disclaimer_text: str = DEFAULT_TOP_DISCLAIMER_TEXT
    show_confidentiality_notice: bool = False
    confidentiality_notice_text: str = DEFAULT_CONFIDENTIALITY_NOTICE_TEXT
    position: int
    questions: List[Any]

    model_config = ConfigDict(from_attributes=True)


class PackageBase(BaseModel):
    title: str
    description: Optional[str] = None
    target_role: Optional[str] = None


class PackageCreate(PackageBase):
    # Transitional: the corporate is derived from the authenticated HR user once
    # admin CRUD moves to supabase-js (Phase 4). Kept for the interim REST path.
    organization_name: str
    tests: List[AssessmentIn] = Field(default_factory=list)
    questions: List[Any] = Field(default_factory=list)


class PackageUpdate(PackageBase):
    """Partial package update; extra keys are ignored so clients can send cart fields."""

    model_config = ConfigDict(extra="ignore")

    title: Optional[str] = None
    target_role: Optional[str] = None
    questions: Optional[List[Any]] = None


class PackageResponse(PackageBase):
    id: uuid.UUID
    corporate_id: uuid.UUID
    access_code: str
    is_active: bool
    created_at: datetime
    updated_at: datetime
    candidate_count: Optional[int] = None

    model_config = ConfigDict(from_attributes=True)
