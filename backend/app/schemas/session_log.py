from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel


class CandidateSessionLogItem(BaseModel):
    id: UUID
    corporate_id: UUID
    candidate_id: UUID
    assessment_id: Optional[UUID] = None
    assessment_name: Optional[str] = None
    event_type: str
    occurred_at: datetime
    duration_seconds: Optional[int] = None
    device_id: Optional[str] = None
    browser: Optional[str] = None
    ip_hash: Optional[str] = None

    model_config = {"from_attributes": True}


class CandidateSessionLogListResponse(BaseModel):
    items: list[CandidateSessionLogItem]
