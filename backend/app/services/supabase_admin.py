"""Supabase Auth Admin helpers (service_role only — never import from the browser)."""
from __future__ import annotations

from typing import Any
from uuid import UUID

from supabase import create_client

from app.config import settings


class SupabaseAdminError(Exception):
    """Raised when Auth Admin API calls fail or are misconfigured."""


def _admin_client():
    """Build a service-role Supabase client for Auth Admin operations.

    Returns:
        A supabase-py client authenticated with the service role key.

    Raises:
        SupabaseAdminError: URL or service role key is missing or malformed.
    """
    url = (settings.SUPABASE_URL or "").rstrip("/")
    key = (settings.SUPABASE_SERVICE_ROLE_KEY or "").strip()
    if not url or not key:
        raise SupabaseAdminError(
            "Supabase Auth Admin is not configured. Set SUPABASE_URL and "
            "SUPABASE_SERVICE_ROLE_KEY on the API server."
        )
    if key.count(".") != 2 and not key.startswith("sb_secret_"):
        raise SupabaseAdminError(
            "SUPABASE_SERVICE_ROLE_KEY is not a Supabase service role key (expected a "
            "JWT like 'eyJ...' or an 'sb_secret_...' key). Copy the service_role key "
            "from `supabase status` (local) or Dashboard > Settings > API (hosted)."
        )
    return create_client(url, key)


def _as_dict(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    if isinstance(value, dict):
        return value
    dump = getattr(value, "model_dump", None)
    if callable(dump):
        dumped = dump()
        return dumped if isinstance(dumped, dict) else {}
    return getattr(value, "__dict__", {}) or {}


def _user_id_from_payload(payload: Any) -> UUID | None:
    """Extract a user UUID from invite / list-users response shapes.

    Args:
        payload: Auth Admin JSON, UserResponse, or User object.

    Returns:
        Parsed UUID, or None when the payload has no id.
    """
    data = _as_dict(payload)
    raw = data.get("id")
    if not raw and isinstance(data.get("user"), (dict, object)):
        raw = _as_dict(data.get("user")).get("id") or getattr(data.get("user"), "id", None)
    if not raw:
        raw = getattr(payload, "id", None)
    if not raw:
        user = getattr(payload, "user", None)
        raw = getattr(user, "id", None) if user is not None else None
    if not raw:
        return None
    try:
        return UUID(str(raw))
    except (TypeError, ValueError):
        return None


def _lookup_user_id_by_email(client: Any, email: str) -> UUID | None:
    """Find an existing Auth user id by email (already-registered invite).

    Args:
        client: Service-role supabase client.
        email: Normalized email.

    Returns:
        Matching user UUID, or None if listing is unsupported / empty.
    """
    admin = getattr(getattr(client, "auth", None), "admin", None)
    if admin is None:
        return None
    lister = getattr(admin, "list_users", None)
    if not callable(lister):
        return None
    try:
        listed = lister()
    except TypeError:
        listed = lister(page=1, per_page=200)
    except Exception:
        return None

    users = listed
    if isinstance(listed, dict):
        users = listed.get("users") or listed.get("data") or []
    else:
        users = getattr(listed, "users", None) or getattr(listed, "data", None) or listed
    if not isinstance(users, list):
        return None
    target = email.lower()
    for row in users:
        row_email = str(_as_dict(row).get("email") or getattr(row, "email", "") or "").lower()
        if row_email == target:
            return _user_id_from_payload(row)
    return None


_ALREADY_REGISTERED_MARKERS = ("already registered", "already been registered", "already exists", "email_exists")


def _normalize_email(email: str) -> str:
    """Lowercase and minimally validate an email address.

    Args:
        email: Raw email input.

    Returns:
        Trimmed, lowercased email.

    Raises:
        SupabaseAdminError: The value is not a plausible email address.
    """
    normalized = (email or "").strip().lower()
    if "@" not in normalized or "." not in normalized.split("@", 1)[-1]:
        raise SupabaseAdminError("A valid email address is required")
    return normalized


def ensure_auth_user(email: str) -> UUID:
    """Create (or find) a confirmed Supabase Auth user without sending email.

    Used by seed/provisioning scripts. ``email_confirm=True`` marks the address
    verified so the user can immediately sign in with an email OTP.

    Args:
        email: Login email for the Auth user.

    Returns:
        The Auth user UUID (``auth.users.id``), new or pre-existing.

    Raises:
        SupabaseAdminError: Missing config, unexpected Auth API failure, or the
            user exists but cannot be resolved by email.
    """
    normalized = _normalize_email(email)
    client = _admin_client()
    try:
        response = client.auth.admin.create_user({"email": normalized, "email_confirm": True})
    except Exception as exc:
        message = str(exc).strip() or "Auth user creation failed"
        if not any(marker in message.lower() for marker in _ALREADY_REGISTERED_MARKERS):
            raise SupabaseAdminError(message[:500]) from exc
        existing = _lookup_user_id_by_email(client, normalized)
        if existing is None:
            raise SupabaseAdminError(
                f"Auth user {normalized} exists but could not be resolved by email"
            ) from exc
        return existing

    user_id = _user_id_from_payload(response) or _lookup_user_id_by_email(client, normalized)
    if user_id is None:
        raise SupabaseAdminError("Auth user creation succeeded but returned no user id")
    return user_id


def invite_hr_user_by_email(email: str, redirect_to: str | None = None) -> UUID:
    """Send a Supabase Auth invite and return the Auth user id.

    Role is persisted in ``public.hr_users`` (not ``user_metadata``). The
    custom access token hook copies tenancy from that table into JWT
    ``app_metadata``.

    Args:
        email: Work email to invite.
        redirect_to: Post-confirm URL (must be on the Auth allow-list).
            Defaults to ``{FRONTEND_URL}/client/dashboard``.

    Returns:
        Auth user UUID for ``hr_users.user_id``.

    Raises:
        SupabaseAdminError: Missing config, Auth API failure, or missing user id.
    """
    normalized = _normalize_email(email)

    destination = (redirect_to or "").strip() or (
        f"{settings.FRONTEND_URL.rstrip('/')}/client/dashboard"
    )
    client = _admin_client()
    options = {"redirect_to": destination}
    try:
        try:
            response = client.auth.admin.invite_user_by_email(normalized, options=options)
        except TypeError:
            response = client.auth.admin.invite_user_by_email(normalized, options)
    except Exception as exc:
        existing = _lookup_user_id_by_email(client, normalized)
        if existing is not None:
            return existing
        message = str(exc).strip() or "Auth invite failed"
        raise SupabaseAdminError(message[:500]) from exc

    user_id = _user_id_from_payload(response)
    if user_id is None:
        user_id = _lookup_user_id_by_email(client, normalized)
    if user_id is None:
        raise SupabaseAdminError("Auth invite succeeded but returned no user id")
    return user_id
