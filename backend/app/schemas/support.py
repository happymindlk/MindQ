from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, Field


class SupportSubmitRequest(BaseModel):
    details: str = Field(min_length=1, max_length=4000)
    candidate_id: Optional[UUID] = None
    path: Optional[str] = None
    user_agent: Optional[str] = None


class SupportSubmitResponse(BaseModel):
    id: UUID
    created_at: datetime


class PublicTrackCandidate(BaseModel):
    full_name: str
    status: str
    progress: str
    avg_score: Optional[float] = None
    jd_fit: Optional[float] = None


class PublicTrackResponse(BaseModel):
    package_title: str
    corporate_name: Optional[str] = None
    candidates: list[PublicTrackCandidate]
