"""Verify an email and password with Supabase Auth without returning the session to the client."""
from __future__ import annotations

import logging
from dataclasses import dataclass
from uuid import UUID

import httpx
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.config import settings

logger = logging.getLogger("app.admin_auth")


class SupabaseAuthUnavailable(Exception):
    """Auth server is misconfigured, redirected, or returned an unexpected body."""


@dataclass(frozen=True)
class SupabasePasswordSession:
    """Session minted by a password grant. Hold it server-side until OTP succeeds."""

    user_id: UUID
    email: str
    access_token: str
    refresh_token: str
    expires_in: int


class _GoTrueUser(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: UUID
    email: str | None = None


class _GoTrueSession(BaseModel):
    """Subset of a GoTrue password-grant body. Extra fields are ignored."""

    model_config = ConfigDict(extra="ignore")

    access_token: str = Field(min_length=20)
    refresh_token: str = Field(min_length=1)
    expires_in: int = Field(gt=0, le=60 * 60 * 24 * 30)
    user: _GoTrueUser


def _api_key() -> str:
    key = (settings.SUPABASE_SERVICE_ROLE_KEY or "").strip()
    if not key or not (settings.SUPABASE_URL or "").strip():
        raise SupabaseAuthUnavailable("Supabase Auth is not configured")
    return key


async def verify_supabase_password(email: str, password: str) -> SupabasePasswordSession | None:
    """Check credentials against GoTrue's password grant.

    A match returns the new session so the caller can withhold it until a
    second factor succeeds. Invalid credentials return None. The response
    body is never logged (it contains tokens).

    Args:
        email: Normalized admin email.
        password: Plain password from the login request.

    Returns:
        The new Supabase session, or None when the credentials are rejected.

    Raises:
        SupabaseAuthUnavailable: Auth is not configured, unreachable, redirected,
            or returned a 200 body that is not a session.
    """
    key = _api_key()
    url = f"{settings.SUPABASE_URL.rstrip('/')}/auth/v1/token?grant_type=password"
    headers = {
        "apikey": key,
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
    }
    try:
        async with httpx.AsyncClient(timeout=10.0, follow_redirects=False) as client:
            response = await client.post(
                url, headers=headers, json={"email": email, "password": password}
            )
    except httpx.HTTPError as exc:
        logger.error(
            "admin_password_grant_unreachable",
            extra={"event": "admin_password_grant_unreachable", "error_type": type(exc).__name__},
        )
        raise SupabaseAuthUnavailable("Authentication service is unavailable") from exc

    if response.status_code in {301, 302, 303, 307, 308}:
        logger.error(
            "admin_password_grant_redirected",
            extra={"event": "admin_password_grant_redirected", "status_code": response.status_code},
        )
        raise SupabaseAuthUnavailable("Authentication service is unavailable")

    if response.status_code in {400, 401, 403, 422}:
        return None
    if response.status_code != 200:
        logger.error(
            "admin_password_grant_failed",
            extra={"event": "admin_password_grant_failed", "status_code": response.status_code},
        )
        raise SupabaseAuthUnavailable("Authentication service is unavailable")

    try:
        parsed = _GoTrueSession.model_validate(response.json())
    except (ValidationError, ValueError) as exc:
        logger.error(
            "admin_password_grant_unexpected_shape",
            extra={"event": "admin_password_grant_unexpected_shape", "error_type": type(exc).__name__},
        )
        raise SupabaseAuthUnavailable("Authentication service is unavailable") from exc

    return SupabasePasswordSession(
        user_id=parsed.user.id,
        email=(parsed.user.email or email).strip().lower(),
        access_token=parsed.access_token,
        refresh_token=parsed.refresh_token,
        expires_in=parsed.expires_in,
    )


async def revoke_supabase_session(access_token: str) -> None:
    """Best-effort logout of a session that must not survive a failed second factor.

    Args:
        access_token: Access token from the password grant. Not logged.
    """
    if not access_token:
        return
    try:
        key = _api_key()
    except SupabaseAuthUnavailable:
        logger.error(
            "admin_session_revoke_unconfigured",
            extra={"event": "admin_session_revoke_unconfigured"},
        )
        return
    url = f"{settings.SUPABASE_URL.rstrip('/')}/auth/v1/logout?scope=local"
    headers = {"apikey": key, "Authorization": f"Bearer {access_token}"}
    try:
        async with httpx.AsyncClient(timeout=10.0, follow_redirects=False) as client:
            response = await client.post(url, headers=headers)
    except httpx.HTTPError as exc:
        logger.error(
            "admin_session_revoke_failed",
            extra={"event": "admin_session_revoke_failed", "error_type": type(exc).__name__},
        )
        return
    if response.status_code not in {200, 204}:
        logger.error(
            "admin_session_revoke_rejected",
            extra={"event": "admin_session_revoke_rejected", "status_code": response.status_code},
        )
