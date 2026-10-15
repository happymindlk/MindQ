import uuid
from datetime import datetime
from typing import Optional
from pydantic import BaseModel, ConfigDict, EmailStr


class CorporateBase(BaseModel):
    name: str
    slug: str


class CorporateCreate(CorporateBase):
    pass


class CorporateResponse(CorporateBase):
    id: uuid.UUID
    logo_url: Optional[str] = None
    primary_color: Optional[str] = None
    contact_email: Optional[EmailStr] = None
    contact_phone: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)
