"""Request and response contracts for HR/client email-OTP login."""
from __future__ import annotations

from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, StringConstraints, field_validator

from app.schemas.client_package import ClientCorporate


class HrOtpSendRequest(BaseModel):
    """Ask for a one-time code for a registered HR/client email."""

    model_config = ConfigDict(extra="forbid")

    email: EmailStr


class HrOtpChallengeResponse(BaseModel):
    """Proof that a code was sent. ``temp_token`` cannot call client APIs."""

    model_config = ConfigDict(extra="forbid")

    status: Literal["otp_required"] = "otp_required"
    temp_token: Annotated[str, StringConstraints(min_length=20, max_length=4096)]


class HrOtpVerifyRequest(BaseModel):
    """Temp token from send plus the emailed six-digit code."""

    model_config = ConfigDict(extra="forbid")

    email: EmailStr
    temp_token: Annotated[str, StringConstraints(strip_whitespace=True, min_length=20, max_length=4096)]
    otp_code: Annotated[str, StringConstraints(strip_whitespace=True, min_length=6, max_length=6, pattern=r"^\d{6}$")]

    @field_validator("temp_token", "otp_code", mode="before")
    @classmethod
    def _strip(cls, value: object) -> object:
        """Trim surrounding whitespace without accepting internal spaces.

        Args:
            value: Raw JSON value.

        Returns:
            Stripped string, or the original value when it is not a string.
        """
        if isinstance(value, str):
            return value.strip()
        return value


class HrProfile(BaseModel):
    """HR membership returned after the code is accepted."""

    model_config = ConfigDict(extra="forbid")

    id: UUID
    email: str
    full_name: str | None = None
    role: str
    corporate_id: UUID


class HrTokenResponse(BaseModel):
    """Backend-minted client-portal session (same shape the portal stores)."""

    model_config = ConfigDict(extra="forbid")

    access_token: str
    token_type: Literal["bearer"] = "bearer"
    expires_in: int
    corporate: ClientCorporate
    user: HrProfile
