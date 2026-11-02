"""Request and response contracts for admin email-OTP login."""
from __future__ import annotations

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field, SecretStr, field_validator


class AdminLoginRequest(BaseModel):
    """Email and password. A match does not return an admin session."""

    model_config = ConfigDict(extra="forbid")

    email: EmailStr
    password: SecretStr = Field(min_length=1, max_length=256)


class AdminLoginChallengeResponse(BaseModel):
    """Proof that a code was sent. ``temp_token`` cannot call admin APIs."""

    model_config = ConfigDict(extra="forbid")

    status: Literal["otp_required"]
    temp_token: str = Field(min_length=20, max_length=4096)


class AdminVerifyOtpRequest(BaseModel):
    """Temp token from login plus the emailed six-digit code."""

    model_config = ConfigDict(extra="forbid")

    temp_token: str = Field(min_length=20, max_length=4096)
    otp_code: str = Field(min_length=6, max_length=6, pattern=r"^\d{6}$")

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


class AdminProfile(BaseModel):
    """Ops membership returned after the code is accepted."""

    model_config = ConfigDict(extra="forbid")

    id: UUID
    email: str
    full_name: str | None = None
    role: str
    corporate_id: UUID


class AdminTokenResponse(BaseModel):
    """Supabase session held server-side until the code was accepted."""

    model_config = ConfigDict(extra="forbid")

    access_token: str
    refresh_token: str
    token_type: Literal["bearer"] = "bearer"
    expires_in: int = Field(gt=0)
    user: AdminProfile


class AdminForgotPasswordRequest(BaseModel):
    """Self-serve password reset request for an ops admin email."""

    model_config = ConfigDict(extra="forbid")

    email: EmailStr


class AdminForgotPasswordResponse(BaseModel):
    """Enumeration-safe confirmation after a reset request."""

    model_config = ConfigDict(extra="forbid")

    detail: str


class AdminChangePasswordRequest(BaseModel):
    """Authenticated password change that requires the current password."""

    model_config = ConfigDict(extra="forbid")

    current_password: SecretStr = Field(min_length=1, max_length=256)
    new_password: SecretStr = Field(min_length=8, max_length=256)


class AdminChangePasswordResponse(BaseModel):
    """Empty success body for password change."""

    model_config = ConfigDict(extra="forbid")

    detail: str = "Password updated."
