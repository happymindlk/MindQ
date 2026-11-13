"""Super Admin Team management: list/grant/revoke over hr_users ops roles."""
from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.v1.admin_ops import router as admin_router
from app.auth import HRUserContext, get_current_ops_user
from app.database import get_db
from app.models.hr_user import HRUser
from app.schemas.admin_team import AdminTeamMember
from app.services.admin_otp import AdminLoginError, _ops_membership, start_admin_login
from app.services.admin_team import (
    AdminTeamError,
    grant_admin,
    is_env_managed_email,
    list_admin_team,
    revoke_admin,
)
from app.services.supabase_password import SupabasePasswordSession


def _scalar(value: object) -> MagicMock:
    result = MagicMock()
    result.scalar_one_or_none.return_value = value
    return result


def _all_rows(rows: list[object]) -> MagicMock:
    result = MagicMock()
    result.all.return_value = rows
    result.first.return_value = rows[0] if rows else None
    result.scalar_one_or_none.return_value = None
    return result


def _session() -> MagicMock:
    session = MagicMock()
    session.execute = AsyncMock()
    session.commit = AsyncMock()
    session.rollback = AsyncMock()
    session.delete = AsyncMock()
    session.flush = AsyncMock()
    return session


def _client(
    session: MagicMock,
    *,
    ops_user_id=None,
    ops_corporate_id=None,
    ops_email: str = "caller@mindq.com",
) -> TestClient:
    application = FastAPI()
    application.include_router(admin_router, prefix="/admin")

    async def _db():
        yield session

    actor_id = ops_user_id or uuid4()
    corp_id = ops_corporate_id or uuid4()

    async def _ops():
        return HRUserContext(
            user_id=actor_id,
            corporate_id=corp_id,
            email=ops_email,
            role="admin",
        )

    application.dependency_overrides[get_db] = _db
    application.dependency_overrides[get_current_ops_user] = _ops
    return TestClient(application), actor_id, corp_id


# --------------------------------------------------------------------------- helpers


def test_is_env_managed_email_uses_ops_admin_emails(monkeypatch):
    monkeypatch.setattr(
        "app.services.admin_team.settings.OPS_ADMIN_EMAILS",
        ["ops@mindq.com", "bootstrap@mindq.com"],
    )
    assert is_env_managed_email("OPS@mindq.com") is True
    assert is_env_managed_email("other@mindq.com") is False


# --------------------------------------------------------------------------- GET /admin/team


@pytest.mark.asyncio
async def test_list_admin_team_merges_database_and_env(monkeypatch):
    monkeypatch.setattr(
        "app.services.admin_team.settings.OPS_ADMIN_EMAILS",
        ["env-only@mindq.com", "db-and-env@mindq.com"],
    )
    caller_id = uuid4()
    db_user = uuid4()
    env_db_user = uuid4()
    created = datetime.now(timezone.utc)
    session = _session()
    session.execute.return_value = _all_rows(
        [
            (db_user, "db@mindq.com", "DB Admin", "admin", created),
            (env_db_user, "db-and-env@mindq.com", "Env DB", "owner", created),
        ]
    )

    members = await list_admin_team(
        session, caller_user_id=caller_id, caller_email="caller@mindq.com"
    )

    by_email = {m.email: m for m in members}
    assert set(by_email) == {
        "db@mindq.com",
        "db-and-env@mindq.com",
        "env-only@mindq.com",
    }
    assert by_email["db@mindq.com"].source == "database"
    assert by_email["db@mindq.com"].can_revoke is True
    assert by_email["db-and-env@mindq.com"].source == "env"
    assert by_email["db-and-env@mindq.com"].can_revoke is False
    assert by_email["env-only@mindq.com"].user_id is None
    assert by_email["env-only@mindq.com"].can_revoke is False


def test_get_team_requires_ops_role():
    session = _session()
    application = FastAPI()
    application.include_router(admin_router, prefix="/admin")

    async def _db():
        yield session

    application.dependency_overrides[get_db] = _db
    # No get_current_ops_user override → real dependency fails without auth.
    res = TestClient(application).get("/admin/team")
    assert res.status_code in {401, 403, 422}


def test_get_team_returns_members(monkeypatch):
    session = _session()
    client, actor_id, _ = _client(session)
    expected = [
        AdminTeamMember(
            user_id=actor_id,
            email="caller@mindq.com",
            name="Caller",
            role="admin",
            source="database",
            can_revoke=False,
        )
    ]

    async def _fake_list(_db, *, caller_user_id, caller_email):
        assert caller_user_id == actor_id
        assert caller_email == "caller@mindq.com"
        return expected

    with patch("app.api.v1.admin_ops.list_admin_team", new=_fake_list):
        res = client.get("/admin/team")

    assert res.status_code == 200
    body = res.json()
    assert len(body["members"]) == 1
    assert body["members"][0]["email"] == "caller@mindq.com"
    assert body["members"][0]["can_revoke"] is False


# --------------------------------------------------------------------------- POST /admin/team


@pytest.mark.asyncio
async def test_grant_admin_upserts_ops_membership_and_audits(monkeypatch):
    actor_id = uuid4()
    corp_id = uuid4()
    new_user_id = uuid4()
    session = _session()
    membership = HRUser(
        user_id=new_user_id,
        corporate_id=corp_id,
        full_name="New Admin",
        role="admin",
    )
    membership.created_at = datetime.now(timezone.utc)

    reload = MagicMock()
    reload.scalar_one.return_value = membership
    reload.scalar_one_or_none.return_value = membership
    # find_ops_role_for_email → None; resolve corporate → corp_id; upsert; reload
    session.execute.side_effect = [
        _scalar(None),  # find_ops_role_for_email
        _scalar(corp_id),  # preferred corporate active
        MagicMock(),  # upsert execute
        reload,  # reload membership
    ]

    monkeypatch.setattr("app.services.admin_team.settings.OPS_ADMIN_EMAILS", [])
    with (
        patch(
            "app.services.admin_team.run_in_threadpool",
            new=AsyncMock(return_value=new_user_id),
        ),
        patch("app.services.admin_team.log_admin_granted") as audit,
    ):
        member = await grant_admin(
            session,
            actor_id=actor_id,
            actor_corporate_id=corp_id,
            email=" New.Admin@mindq.com ",
            name="New Admin",
        )

    assert member.email == "new.admin@mindq.com"
    assert member.user_id == new_user_id
    assert member.source == "database"
    assert member.can_revoke is True
    session.commit.assert_awaited()
    audit.assert_called_once()
    assert audit.call_args.kwargs["target_email"] == "new.admin@mindq.com"


@pytest.mark.asyncio
async def test_grant_admin_rejects_duplicate_ops():
    session = _session()
    session.execute.return_value = _scalar("admin")

    with pytest.raises(AdminTeamError) as exc:
        await grant_admin(
            session,
            actor_id=uuid4(),
            actor_corporate_id=uuid4(),
            email="existing@mindq.com",
        )
    assert exc.value.status_code == 409


def test_post_team_grants_via_route():
    session = _session()
    client, actor_id, corp_id = _client(session)
    member = AdminTeamMember(
        user_id=uuid4(),
        email="new@mindq.com",
        name="New",
        role="admin",
        source="database",
        can_revoke=True,
    )

    async def _fake_grant(_db, **kwargs):
        assert kwargs["actor_id"] == actor_id
        assert kwargs["actor_corporate_id"] == corp_id
        assert kwargs["email"] == "new@mindq.com"
        return member

    with patch("app.api.v1.admin_ops.grant_admin", new=_fake_grant):
        res = client.post("/admin/team", json={"email": "New@mindq.com"})

    assert res.status_code == 200
    assert res.json()["member"]["email"] == "new@mindq.com"


def test_post_team_rejects_invalid_email():
    session = _session()
    client, _, _ = _client(session)
    res = client.post("/admin/team", json={"email": "not-an-email"})
    assert res.status_code == 422


# --------------------------------------------------------------------------- DELETE /admin/team/{id}


@pytest.mark.asyncio
async def test_revoke_admin_deletes_membership_and_audits(monkeypatch):
    actor_id = uuid4()
    target_id = uuid4()
    session = _session()
    email_result = MagicMock()
    email_result.first.return_value = SimpleNamespace(
        email="target@mindq.com", role="admin"
    )
    delete_result = MagicMock()
    delete_result.rowcount = 1
    session.execute.side_effect = [email_result, delete_result]

    monkeypatch.setattr("app.services.admin_team.settings.OPS_ADMIN_EMAILS", [])
    with patch("app.services.admin_team.log_admin_revoked") as audit:
        await revoke_admin(
            session,
            actor_id=actor_id,
            actor_email="caller@mindq.com",
            target_user_id=target_id,
        )

    assert session.execute.await_count == 2
    session.commit.assert_awaited()
    audit.assert_called_once()
    assert audit.call_args.kwargs["target_user_id"] == target_id


@pytest.mark.asyncio
async def test_revoke_rejects_self_by_user_id():
    actor_id = uuid4()
    session = _session()
    with pytest.raises(AdminTeamError) as exc:
        await revoke_admin(
            session,
            actor_id=actor_id,
            actor_email="caller@mindq.com",
            target_user_id=actor_id,
        )
    assert exc.value.status_code == 400
    assert "own" in exc.value.detail.lower()
    session.execute.assert_not_called()


@pytest.mark.asyncio
async def test_revoke_rejects_self_by_email():
    actor_id = uuid4()
    target_id = uuid4()
    session = _session()
    email_result = MagicMock()
    email_result.first.return_value = SimpleNamespace(
        email="caller@mindq.com", role="admin"
    )
    session.execute.side_effect = [email_result]

    with pytest.raises(AdminTeamError) as exc:
        await revoke_admin(
            session,
            actor_id=actor_id,
            actor_email="Caller@mindq.com",
            target_user_id=target_id,
        )
    assert exc.value.status_code == 400
    assert "own" in exc.value.detail.lower()


@pytest.mark.asyncio
async def test_revoke_rejects_env_managed(monkeypatch):
    actor_id = uuid4()
    target_id = uuid4()
    session = _session()
    email_result = MagicMock()
    email_result.first.return_value = SimpleNamespace(
        email="bootstrap@mindq.com", role="admin"
    )
    session.execute.side_effect = [email_result]
    monkeypatch.setattr(
        "app.services.admin_team.settings.OPS_ADMIN_EMAILS",
        ["bootstrap@mindq.com"],
    )

    with pytest.raises(AdminTeamError) as exc:
        await revoke_admin(
            session,
            actor_id=actor_id,
            actor_email="caller@mindq.com",
            target_user_id=target_id,
        )
    assert exc.value.status_code == 400
    assert "env" in exc.value.detail.lower()


def test_delete_team_member_route_maps_errors():
    session = _session()
    client, actor_id, _ = _client(session)
    target_id = uuid4()

    async def _fake_revoke(_db, **kwargs):
        assert kwargs["actor_id"] == actor_id
        raise AdminTeamError(400, "You cannot revoke your own Super Admin access")

    with patch("app.api.v1.admin_ops.revoke_admin", new=_fake_revoke):
        res = client.delete(f"/admin/team/{target_id}")

    assert res.status_code == 400
    assert "own" in res.json()["detail"].lower()


def test_delete_team_member_returns_204():
    session = _session()
    client, _, _ = _client(session)
    target_id = uuid4()

    async def _fake_revoke(_db, **_kwargs):
        return None

    with patch("app.api.v1.admin_ops.revoke_admin", new=_fake_revoke):
        res = client.delete(f"/admin/team/{target_id}")

    assert res.status_code == 204


# --------------------------------------------------------------------------- OTP after grant / revoke


@pytest.mark.asyncio
async def test_ops_membership_allows_granted_admin():
    user_id = uuid4()
    session = _session()
    session.execute.return_value = _scalar(
        HRUser(user_id=user_id, corporate_id=uuid4(), full_name="A", role="admin")
    )
    row = await _ops_membership(session, user_id, email="a@mindq.com")
    assert row is not None
    assert row.role == "admin"


@pytest.mark.asyncio
async def test_ops_membership_blocks_revoked_user():
    user_id = uuid4()
    session = _session()
    session.execute.return_value = _scalar(None)
    with patch("app.services.admin_otp.is_env_managed_email", return_value=False):
        row = await _ops_membership(session, user_id, email="revoked@mindq.com")
    assert row is None


@pytest.mark.asyncio
async def test_start_admin_login_succeeds_after_grant(monkeypatch):
    user_id = uuid4()
    corp_id = uuid4()
    session = _session()
    membership = HRUser(
        user_id=user_id, corporate_id=corp_id, full_name="Granted", role="admin"
    )

    password_session = SupabasePasswordSession(
        user_id=user_id,
        email="granted@mindq.com",
        access_token="access",
        refresh_token="refresh",
        expires_in=3600,
    )

    async def fake_verify(email, password):
        assert email == "granted@mindq.com"
        return password_session

    monkeypatch.setattr(
        "app.services.admin_otp.verify_supabase_password", fake_verify
    )
    monkeypatch.setattr(
        "app.services.admin_otp._ops_membership",
        AsyncMock(return_value=membership),
    )
    monkeypatch.setattr("app.services.admin_otp._retire_expired", AsyncMock())
    monkeypatch.setattr("app.services.admin_otp._is_locked", AsyncMock(return_value=False))
    monkeypatch.setattr("app.services.admin_otp._recent_sends", AsyncMock(return_value=[]))
    monkeypatch.setattr("app.services.admin_otp._supersede_open", AsyncMock(return_value=[]))
    monkeypatch.setattr("app.services.admin_otp.send_admin_otp_email", AsyncMock())
    monkeypatch.setattr(
        "app.services.admin_otp.revoke_supabase_session", AsyncMock()
    )
    session.execute = AsyncMock(return_value=MagicMock())

    result = await start_admin_login(session, "Granted@mindq.com", "secret")
    assert result.status == "otp_required"
    assert result.temp_token


@pytest.mark.asyncio
async def test_start_admin_login_forbidden_immediately_after_revoke(monkeypatch):
    user_id = uuid4()
    password_session = SupabasePasswordSession(
        user_id=user_id,
        email="revoked@mindq.com",
        access_token="access",
        refresh_token="refresh",
        expires_in=3600,
    )

    async def fake_verify(email, password):
        return password_session

    monkeypatch.setattr(
        "app.services.admin_otp.verify_supabase_password", fake_verify
    )
    monkeypatch.setattr(
        "app.services.admin_otp._ops_membership",
        AsyncMock(return_value=None),
    )
    discard = AsyncMock()
    monkeypatch.setattr("app.services.admin_otp._discard_password_session", discard)

    with pytest.raises(AdminLoginError) as exc:
        await start_admin_login(AsyncMock(), "revoked@mindq.com", "secret")

    assert exc.value.status_code == 403
    discard.assert_awaited()
