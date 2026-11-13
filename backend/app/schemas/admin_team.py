"""Request and response contracts for Super Admin Team management."""
from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator


class AdminTeamMember(BaseModel):
    """One Super Admin entry (database membership and/or env bootstrap)."""

    model_config = ConfigDict(extra="forbid")

    user_id: UUID | None = None
    email: str
    name: str | None = None
    role: str | None = None
    source: Literal["database", "env"]
    is_active: bool = True
    created_at: datetime | None = None
    can_revoke: bool = False


class AdminTeamListResponse(BaseModel):
    """All Super Admins visible to an authenticated ops caller."""

    model_config = ConfigDict(extra="forbid")

    members: list[AdminTeamMember]


class AdminTeamGrantRequest(BaseModel):
    """Grant Super Admin access to an email."""

    model_config = ConfigDict(extra="forbid")

    email: EmailStr
    name: str | None = Field(default=None, max_length=255)

    @field_validator("email", mode="before")
    @classmethod
    def _normalize_email(cls, value: object) -> object:
        """Lowercase and trim the email before EmailStr validation.

        Args:
            value: Raw JSON value.

        Returns:
            Normalized string, or the original value when not a string.
        """
        if isinstance(value, str):
            return value.strip().lower()
        return value

    @field_validator("name", mode="before")
    @classmethod
    def _strip_name(cls, value: object) -> object:
        """Trim optional display name; blank becomes None.

        Args:
            value: Raw JSON value.

        Returns:
            Stripped string, None for blanks, or the original value.
        """
        if value is None:
            return None
        if isinstance(value, str):
            cleaned = value.strip()
            return cleaned or None
        return value


class AdminTeamGrantResponse(BaseModel):
    """Acknowledgement after granting Super Admin access."""

    model_config = ConfigDict(extra="forbid")

    member: AdminTeamMember
