from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, EmailStr, Field, field_validator, model_validator


class SupportSubmitRequest(BaseModel):
    """Public technical-support report payload (pre- or post-login)."""

    email: EmailStr
    contact_number: str = Field(min_length=1, max_length=64)
    details: Optional[str] = Field(default=None, max_length=4000)
    description: Optional[str] = Field(default=None, max_length=4000)
    candidate_id: Optional[UUID] = None
    access_code: Optional[str] = Field(default=None, max_length=36)
    package_code: Optional[str] = Field(default=None, max_length=36)
    entered_name: Optional[str] = Field(default=None, max_length=255)
    issue_category: Optional[str] = Field(default="TECHNICAL", max_length=64)
    device_id: Optional[str] = Field(default=None, max_length=128)
    browser: Optional[str] = None
    page_url: Optional[str] = None
    path: Optional[str] = None
    user_agent: Optional[str] = None

    @field_validator("contact_number")
    @classmethod
    def _validate_contact_number(cls, value: str) -> str:
        trimmed = (value or "").strip()
        digits = "".join(ch for ch in trimmed if ch.isdigit())
        if len(digits) < 7 or len(digits) > 15:
            raise ValueError("contact_number must contain 7–15 digits")
        if not trimmed or not (trimmed[0].isdigit() or trimmed[0] == "+"):
            raise ValueError("contact_number format is invalid")
        return trimmed

    @model_validator(mode="after")
    def _require_description(self) -> "SupportSubmitRequest":
        body = (self.description or self.details or "").strip()
        if not body:
            raise ValueError("description is required")
        self.description = body
        self.details = body
        return self


class SupportSubmitResponse(BaseModel):
    id: UUID
    created_at: datetime


class PublicTrackCandidate(BaseModel):
    full_name: str
    status: str
    progress: str
    avg_score: Optional[float] = None


class PublicTrackResponse(BaseModel):
    package_title: str
    corporate_name: Optional[str] = None
    candidates: list[PublicTrackCandidate]
