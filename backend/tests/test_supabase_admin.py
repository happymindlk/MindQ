"""Unit tests for Auth Admin invite helper."""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest

from app.services.supabase_admin import (
    SupabaseAdminError,
    ensure_auth_user,
    invite_hr_user_by_email,
)


def _client_with(admin: MagicMock) -> SimpleNamespace:
    return SimpleNamespace(auth=SimpleNamespace(admin=admin))


def test_ensure_auth_user_creates_confirmed_user_without_invite():
    user_id = uuid4()
    admin = MagicMock()
    admin.create_user.return_value = SimpleNamespace(user=SimpleNamespace(id=user_id))

    with patch("app.services.supabase_admin._admin_client", return_value=_client_with(admin)):
        result = ensure_auth_user("  HR.Test@Acme.test ")

    assert result == user_id
    admin.create_user.assert_called_once_with(
        {"email": "hr.test@acme.test", "email_confirm": True}
    )
    admin.invite_user_by_email.assert_not_called()


def test_ensure_auth_user_reuses_already_registered_user():
    user_id = uuid4()
    admin = MagicMock()
    admin.create_user.side_effect = RuntimeError(
        "A user with this email address has already been registered"
    )
    admin.list_users.return_value = [SimpleNamespace(id=user_id, email="hr@acme.test")]

    with patch("app.services.supabase_admin._admin_client", return_value=_client_with(admin)):
        assert ensure_auth_user("hr@acme.test") == user_id


def test_ensure_auth_user_registered_but_unresolvable_raises():
    admin = MagicMock()
    admin.create_user.side_effect = RuntimeError("email_exists")
    admin.list_users.return_value = []

    with patch("app.services.supabase_admin._admin_client", return_value=_client_with(admin)):
        with pytest.raises(SupabaseAdminError, match="could not be resolved"):
            ensure_auth_user("hr@acme.test")


def test_ensure_auth_user_surfaces_other_api_errors():
    admin = MagicMock()
    admin.create_user.side_effect = RuntimeError("Invalid API key")

    with patch("app.services.supabase_admin._admin_client", return_value=_client_with(admin)):
        with pytest.raises(SupabaseAdminError, match="Invalid API key"):
            ensure_auth_user("hr@acme.test")
    admin.list_users.assert_not_called()


@pytest.mark.parametrize("bad", ["", "not-an-email", "hr@localhost"])
def test_ensure_auth_user_rejects_invalid_email(bad: str):
    with patch("app.services.supabase_admin._admin_client") as factory:
        with pytest.raises(SupabaseAdminError, match="valid email"):
            ensure_auth_user(bad)
    factory.assert_not_called()


def test_invite_returns_user_id_from_response():
    user_id = uuid4()
    admin = MagicMock()
    admin.invite_user_by_email.return_value = SimpleNamespace(user=SimpleNamespace(id=user_id))
    client = SimpleNamespace(auth=SimpleNamespace(admin=admin))

    with patch("app.services.supabase_admin._admin_client", return_value=client):
        result = invite_hr_user_by_email("hr@acme.test", redirect_to="http://localhost:5173/client/dashboard")

    assert result == user_id
    admin.invite_user_by_email.assert_called()
    kwargs = admin.invite_user_by_email.call_args
    assert kwargs.kwargs.get("options", {}).get("redirect_to") == (
        "http://localhost:5173/client/dashboard"
    ) or (len(kwargs.args) > 1 and kwargs.args[1].get("redirect_to"))


def test_invite_reuses_existing_user_when_auth_rejects_duplicate():
    user_id = uuid4()
    admin = MagicMock()
    admin.invite_user_by_email.side_effect = RuntimeError("User already registered")
    admin.list_users.return_value = [SimpleNamespace(id=user_id, email="hr@acme.test")]
    client = SimpleNamespace(auth=SimpleNamespace(admin=admin))

    with patch("app.services.supabase_admin._admin_client", return_value=client):
        result = invite_hr_user_by_email("hr@acme.test")

    assert result == user_id


def test_invite_requires_service_role_config():
    with patch("app.services.supabase_admin.settings") as settings:
        settings.SUPABASE_URL = "http://127.0.0.1:54321"
        settings.SUPABASE_SERVICE_ROLE_KEY = ""
        with pytest.raises(SupabaseAdminError, match="not configured"):
            invite_hr_user_by_email("hr@acme.test")
