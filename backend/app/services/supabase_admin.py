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


# Auth Admin list paging. GoTrue may cap per_page below this; the loop copes.
_LIST_PAGE_SIZE = 1000
# Hard stop so a misbehaving API cannot loop forever (= 200k users at 1000/page).
_LIST_MAX_PAGES = 200


def _users_from_listing(listed: Any) -> list[Any]:
    """Normalize ``list_users`` responses (list, dict, or model) to a list."""
    if isinstance(listed, list):
        return listed
    if isinstance(listed, dict):
        users = listed.get("users") or listed.get("data") or []
    else:
        users = getattr(listed, "users", None) or getattr(listed, "data", None) or []
    if not isinstance(users, list):
        raise SupabaseAdminError("Auth Admin list_users returned an unexpected shape")
    return users


def _lookup_user_id_by_email(client: Any, email: str) -> UUID | None:
    """Find an existing Auth user id by email, scanning every page.

    The Python Auth Admin SDK has no email filter, so this pages through
    ``list_users`` until the email matches or the pages run out. Earlier code
    read only page 1 (so users past the first page looked "not found") and
    turned API failures into ``None`` (so an Auth outage looked like "not
    registered"). Both now behave correctly: not found -> None, failure ->
    ``SupabaseAdminError`` (callers map that to 503).

    Args:
        client: Service-role supabase client.
        email: Normalized email.

    Returns:
        Matching user UUID, or None when no Auth user has that email.

    Raises:
        SupabaseAdminError: The Admin API is unavailable, errored, or returned
            an unexpected response.
    """
    admin = getattr(getattr(client, "auth", None), "admin", None)
    lister = getattr(admin, "list_users", None) if admin is not None else None
    if not callable(lister):
        raise SupabaseAdminError("Supabase Auth Admin list_users is unavailable")

    target = email.lower()
    largest_page = 0
    for page in range(1, _LIST_MAX_PAGES + 1):
        try:
            listed = lister(page=page, per_page=_LIST_PAGE_SIZE)
        except SupabaseAdminError:
            raise
        except Exception as exc:
            message = str(exc).strip() or type(exc).__name__
            raise SupabaseAdminError(f"Auth user lookup failed: {message[:300]}") from exc
        users = _users_from_listing(listed)
        if not users:
            return None
        for row in users:
            row_email = str(_as_dict(row).get("email") or getattr(row, "email", "") or "").lower()
            if row_email == target:
                return _user_id_from_payload(row)
        # A page shorter than the largest one seen is the last page (works even
        # if the server caps per_page below _LIST_PAGE_SIZE).
        largest_page = max(largest_page, len(users))
        if len(users) < largest_page:
            return None
    raise SupabaseAdminError(
        f"Auth user lookup exceeded {_LIST_MAX_PAGES} pages without finishing"
    )


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


def find_auth_user_id_by_email(email: str) -> UUID | None:
    """Resolve an existing Supabase Auth user id by email, server-side only.

    Identity *resolution* only: no Supabase email is sent and no Supabase
    session is created. HR OTP challenges are issued and verified entirely
    by FastAPI; this lookup just maps the submitted email to the
    ``hr_users.user_id`` provisioned at invite time.

    Args:
        email: Normalized login email.

    Returns:
        The Auth user UUID, or None when no Auth user has that email.

    Raises:
        SupabaseAdminError: Auth Admin is not configured, or the lookup failed
            (never reported as "no such user").
    """
    normalized = _normalize_email(email)
    client = _admin_client()
    return _lookup_user_id_by_email(client, normalized)


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


def generate_password_recovery_link(email: str, redirect_to: str) -> str:
    """Create a one-time password-recovery action link via Auth Admin.

    The link is intended for delivery through our own SES template so we do
    not depend on Supabase SMTP. The browser lands on ``redirect_to`` with a
    recovery session in the URL hash after GoTrue verifies the token.

    Args:
        email: Auth user email to recover.
        redirect_to: Absolute frontend URL (must be on the Auth redirect allow-list).

    Returns:
        Absolute ``action_link`` the user can open to set a new password.

    Raises:
        SupabaseAdminError: Missing config, Auth API failure, or missing link.
    """
    normalized = _normalize_email(email)
    destination = (redirect_to or "").strip()
    if not destination.startswith("http"):
        raise SupabaseAdminError("redirect_to must be an absolute http(s) URL")

    client = _admin_client()
    payload: dict[str, Any] = {
        "type": "recovery",
        "email": normalized,
        "options": {"redirect_to": destination},
    }
    try:
        try:
            response = client.auth.admin.generate_link(payload)
        except TypeError:
            response = client.auth.admin.generate_link(
                {"type": "recovery", "email": normalized, "redirect_to": destination}
            )
    except Exception as exc:
        message = str(exc).strip() or "Password recovery link generation failed"
        raise SupabaseAdminError(message[:500]) from exc

    data = _as_dict(response)
    properties = _as_dict(data.get("properties") or getattr(response, "properties", None))
    action_link = (
        properties.get("action_link")
        or data.get("action_link")
        or getattr(response, "action_link", None)
    )
    if not action_link or not isinstance(action_link, str):
        raise SupabaseAdminError("Auth Admin returned no recovery action_link")
    return action_link.strip()


def update_user_password(user_id: UUID, password: str) -> None:
    """Set a new password for an Auth user via the service-role Admin API.

    Args:
        user_id: ``auth.users.id``.
        password: Plain new password (validated by the caller).

    Raises:
        SupabaseAdminError: Missing config or Auth Admin rejection.
    """
    if not password or len(password) < 8:
        raise SupabaseAdminError("Password must be at least 8 characters")
    client = _admin_client()
    try:
        client.auth.admin.update_user_by_id(str(user_id), {"password": password})
    except Exception as exc:
        message = str(exc).strip() or "Password update failed"
        raise SupabaseAdminError(message[:500]) from exc


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

    from app.services.email import resolve_frontend_origin

    destination = (redirect_to or "").strip() or (
        f"{resolve_frontend_origin()}/client/dashboard"
    )
    client = _admin_client()
    options = {"redirect_to": destination}
    try:
        try:
            response = client.auth.admin.invite_user_by_email(normalized, options=options)
        except TypeError:
            response = client.auth.admin.invite_user_by_email(normalized, options)
    except Exception as exc:
        try:
            existing = _lookup_user_id_by_email(client, normalized)
        except SupabaseAdminError:
            existing = None  # report the original invite failure below
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
