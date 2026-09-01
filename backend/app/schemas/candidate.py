import uuid
from datetime import datetime
from typing import Optional
from pydantic import BaseModel, EmailStr, ConfigDict


class CandidateBase(BaseModel):
    full_name: str
    email: EmailStr


class CandidateLogin(BaseModel):
    full_name: str
    email: EmailStr
    access_code: str


class CandidateResponse(CandidateBase):
    id: uuid.UUID
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
