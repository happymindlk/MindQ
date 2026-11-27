"""P1 Batch B: CORS lockdown, support binding, safe defaults, log hygiene, Auth lookup."""
from __future__ import annotations

import logging
import uuid
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from starlette.requests import Request

from app import main as main_mod
from app.config import Settings
from app.services import email as email_mod
from app.services import supabase_admin
from app.services.supabase_admin import SupabaseAdminError, _lookup_user_id_by_email

# --- P1-07: CORS -------------------------------------------------------------


@pytest.mark.parametrize(
    "origin",
    [
        "https://evil.pages.dev",
        "https://evilmindq.pages.dev",
        "https://mindq.pages.dev.evil.com",
        "https://a.b.mindq.pages.dev",
        "https://x.mindqtalent.com.evil.io",
        "http://feature.mindq.pages.dev",
    ],
)
def test_cors_rejects_foreign_pages_and_lookalikes(origin):
    assert not main_mod.is_origin_allowed(origin)


@pytest.mark.parametrize(
    "origin", ["https://mindq.pages.dev", "https://pr-42.mindq.pages.dev", "https://qa.app.mindqtalent.com"]
)
def test_cors_allows_our_hosts(origin):
    assert main_mod.is_origin_allowed(origin)


def test_production_drops_localhost_even_if_configured(monkeypatch):
    monkeypatch.setattr(main_mod.settings, "ENVIRONMENT", "production")
    monkeypatch.setattr(
        main_mod.settings, "CORS_ORIGINS", "https://qa.app.mindqtalent.com,http://localhost:5173"
    )
    origins = main_mod._build_allowed_origins()
    assert "https://qa.app.mindqtalent.com" in origins
    assert not any("localhost" in o or "127.0.0.1" in o for o in origins)


def test_non_production_keeps_localhost(monkeypatch):
    monkeypatch.setattr(main_mod.settings, "ENVIRONMENT", "qa")
    assert "http://localhost:5173" in main_mod._build_allowed_origins()


# --- P1-09: support ticket binding ------------------------------------------


@pytest.mark.asyncio
async def test_support_ignores_body_candidate_id(async_client, monkeypatch):
    from app.api.v1 import support as support_api
    from app.database import get_db

    captured = {}

    async def _resolve(_db, *, candidate_id, access_code, email):
        captured["candidate_id"] = candidate_id
        return None, None

    monkeypatch.setattr(support_api, "_resolve_candidate_link", _resolve)
    monkeypatch.setattr(support_api, "send_transactional_email", lambda *a, **k: None)

    db = MagicMock()
    db.add = MagicMock()

    async def _commit():
        return None

    async def _refresh(ticket):
        ticket.id = uuid.uuid4()
        from datetime import datetime, timezone

        ticket.created_at = datetime.now(timezone.utc)

    db.commit = _commit
    db.refresh = _refresh

    async def _db():
        yield db

    main_mod.app.dependency_overrides[get_db] = _db
    try:
        res = await async_client.post(
            "/api/v1/support/submit",
            json={
                "email": "a@example.com",
                "contact_number": "+94 77 123 4567",
                "details": "Timer froze on question 4",
                "candidate_id": str(uuid.uuid4()),  # forged: must be ignored
            },
        )
    finally:
        main_mod.app.dependency_overrides.pop(get_db, None)
    assert res.status_code == 200, res.text
    assert captured["candidate_id"] is None


def test_support_token_binding_reads_only_valid_candidate_tokens():
    from app.auth import candidate_id_from_authorization, issue_candidate_token

    cand = SimpleNamespace(id=uuid.uuid4(), corporate_id=uuid.uuid4(), package_id=uuid.uuid4())
    token = issue_candidate_token(cand)
    assert candidate_id_from_authorization(f"Bearer {token}") == cand.id
    assert candidate_id_from_authorization("Bearer not-a-jwt") is None
    assert candidate_id_from_authorization(None) is None
    assert candidate_id_from_authorization("Basic abc") is None


@pytest.mark.asyncio
async def test_support_email_alone_links_nothing():
    from app.api.v1.support import _resolve_candidate_link

    db = MagicMock()

    async def _never(*_a, **_k):  # any DB lookup would be a by-email match
        raise AssertionError("email-only lookup must not query candidates")

    db.execute = _never
    assert await _resolve_candidate_link(
        db, candidate_id=None, access_code=None, email="victim@corp.com"
    ) == (None, None)


# --- P1-14: safe defaults + boot warnings -----------------------------------


def test_debug_defaults_off(monkeypatch):
    monkeypatch.delenv("DEBUG", raising=False)
    assert Settings(_env_file=None).DEBUG is False


def _cfg(**overrides):
    base = dict(
        _env_file=None,
        DEBUG=False,
        ENVIRONMENT="production",
        SECRET_KEY="x" * 40,
        SUPABASE_JWT_SECRET="y" * 40,
        CORS_ORIGINS="https://qa.app.mindqtalent.com",
        FRONTEND_URL="https://qa.app.mindqtalent.com",
    )
    base.update(overrides)
    return Settings(**base)


def test_clean_production_config_has_no_warnings():
    from app.security import production_config_warnings

    assert production_config_warnings(_cfg()) == []


def test_warns_when_environment_unset_or_frontend_missing(caplog):
    from app.security import assert_production_ready

    with caplog.at_level(logging.WARNING, logger="app.security"):
        assert_production_ready(_cfg(ENVIRONMENT="development", FRONTEND_URL=""))  # boots
    logged = "\n".join(r.getMessage() for r in caplog.records)
    assert "ENVIRONMENT is unset" in logged
    assert "FRONTEND_URL is not set" in logged


def test_warns_on_unknown_environment_and_prod_with_debug():
    from app.security import production_config_warnings

    assert any("not one of" in w for w in production_config_warnings(_cfg(ENVIRONMENT="prod")))
    assert any(
        "DEBUG=true" in w for w in production_config_warnings(_cfg(DEBUG=True))
    )


@pytest.mark.asyncio
async def test_debug_endpoint_needs_ops_when_debug_off_even_without_environment(monkeypatch):
    from fastapi import HTTPException

    from app.api.v1 import debug as debug_api

    monkeypatch.setattr(debug_api.settings, "DEBUG", False)
    monkeypatch.setattr(debug_api.settings, "ENVIRONMENT", "development")
    with pytest.raises(HTTPException) as exc:
        await debug_api.sentry_trigger(authorization=None)
    assert exc.value.status_code == 403


# --- P1-15: invite link origin ----------------------------------------------


def _request(headers: dict[str, str]) -> Request:
    return Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/",
            "headers": [(k.lower().encode(), v.encode()) for k, v in headers.items()],
        }
    )


def test_production_never_derives_links_from_headers(monkeypatch):
    monkeypatch.setattr(email_mod.settings, "ENVIRONMENT", "production")
    monkeypatch.setattr(email_mod.settings, "FRONTEND_URL", "")
    monkeypatch.setattr(email_mod.settings, "PORTAL_URL", "")
    origin = email_mod.resolve_frontend_origin(_request({"origin": "https://qa.app.mindqtalent.com"}))
    assert origin == email_mod.PRODUCTION_FRONTEND_URL


def test_non_production_ignores_untrusted_origin(monkeypatch):
    monkeypatch.setattr(email_mod.settings, "ENVIRONMENT", "qa")
    monkeypatch.setattr(email_mod.settings, "FRONTEND_URL", "")
    monkeypatch.setattr(email_mod.settings, "PORTAL_URL", "")
    assert (
        email_mod.resolve_frontend_origin(_request({"origin": "https://phish.example"}))
        == email_mod.PRODUCTION_FRONTEND_URL
    )
    assert (
        email_mod.resolve_frontend_origin(_request({"origin": "https://qa.app.mindqtalent.com"}))
        == "https://qa.app.mindqtalent.com"
    )


def test_redaction_helpers():
    assert email_mod.redact_access_code("HM-ABCDEF-1") == "***-1"
    assert email_mod.redact_access_code("ab") == "***"
    assert (
        email_mod.redact_link("https://qa.app.mindqtalent.com/portal?code=HM-ABCDEF-1")
        == "https://qa.app.mindqtalent.com/portal"
    )


# --- P1-10: Auth Admin lookup ------------------------------------------------


def _client(pages):
    admin = MagicMock()
    admin.list_users.side_effect = pages
    return SimpleNamespace(auth=SimpleNamespace(admin=admin)), admin


def _users(*emails):
    return [SimpleNamespace(id=str(uuid.uuid4()), email=e) for e in emails]


def test_lookup_finds_user_beyond_first_page(monkeypatch):
    monkeypatch.setattr(supabase_admin, "_LIST_PAGE_SIZE", 2)
    target = SimpleNamespace(id=str(uuid.uuid4()), email="hr@acme.test")
    client, admin = _client([_users("a@x.io", "b@x.io"), [target]])
    assert _lookup_user_id_by_email(client, "hr@acme.test") == uuid.UUID(target.id)
    assert [c.kwargs["page"] for c in admin.list_users.call_args_list] == [1, 2]


def test_lookup_returns_none_only_after_last_page(monkeypatch):
    monkeypatch.setattr(supabase_admin, "_LIST_PAGE_SIZE", 2)
    client, admin = _client([_users("a@x.io", "b@x.io"), _users("c@x.io")])
    assert _lookup_user_id_by_email(client, "hr@acme.test") is None
    assert admin.list_users.call_count == 2


def test_lookup_api_failure_raises_instead_of_not_found():
    client, _ = _client([RuntimeError("502 Bad Gateway")])
    with pytest.raises(SupabaseAdminError, match="lookup failed"):
        _lookup_user_id_by_email(client, "hr@acme.test")


def test_lookup_unexpected_shape_raises():
    client, _ = _client([{"users": "nope"}])
    with pytest.raises(SupabaseAdminError):
        _lookup_user_id_by_email(client, "hr@acme.test")
