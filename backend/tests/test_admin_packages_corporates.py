"""Ops GET /admin/packages and GET/PATCH /admin/corporates/{id} behind the ops JWT."""
from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from app.api.v1.admin_ops import router as admin_router
from app.auth import HRUserContext, get_current_ops_user
from app.database import get_db


def _client(session: AsyncMock, *, ops: bool = True) -> TestClient:
    application = FastAPI()
    application.include_router(admin_router, prefix="/admin")

    async def _db():
        yield session

    async def _ops():
        if not ops:
            raise HTTPException(status_code=403, detail="Operations role required")
        return HRUserContext(user_id=uuid4(), corporate_id=uuid4(), role="admin")

    application.dependency_overrides[get_db] = _db
    application.dependency_overrides[get_current_ops_user] = _ops
    return TestClient(application)


def _corporate(**overrides):
    now = datetime(2026, 11, 1, tzinfo=timezone.utc)
    values = {
        "id": uuid4(),
        "name": "Acme",
        "slug": "acme",
        "logo_url": "https://cdn.example.com/logo.png",
        "primary_color": "#7C3AED",
        "contact_email": "hr@acme.example",
        "contact_phone": "+1 555 0100",
        "allowed_hr_emails": ["hr@acme.example"],
        "is_active": True,
        "created_at": now,
        "updated_at": now,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def _session_with_corporate(corporate):
    result = MagicMock()
    result.scalar_one_or_none.return_value = corporate
    session = AsyncMock()
    session.execute = AsyncMock(return_value=result)
    session.commit = AsyncMock()
    session.refresh = AsyncMock()
    return session


# --- GET /admin/packages ------------------------------------------------------


def test_list_packages_passes_through_view_columns():
    row = {
        "id": uuid4(),
        "corporate_id": uuid4(),
        "title": "Backend Engineer",
        "status": "published",
        "access_code": "PKG123",
        "is_active": True,
        "created_at": datetime(2026, 11, 3, tzinfo=timezone.utc),
        "corporate_name": "Acme",
        "corporate_slug": "acme",
        "candidate_count": 4,
    }
    result = MagicMock()
    result.mappings.return_value.all.return_value = [row]
    session = AsyncMock()
    session.execute = AsyncMock(return_value=result)

    res = _client(session).get("/admin/packages")

    assert res.status_code == 200
    body = res.json()
    assert len(body) == 1
    assert body[0]["id"] == str(row["id"])
    assert body[0]["corporate_name"] == "Acme"
    assert body[0]["candidate_count"] == 4
    # Columns outside the declared model (packages.*) are kept.
    assert body[0]["access_code"] == "PKG123"
    assert body[0]["is_active"] is True


def test_list_packages_rejects_non_ops_user():
    session = AsyncMock()

    res = _client(session, ops=False).get("/admin/packages")

    assert res.status_code == 403
    session.execute.assert_not_called()


# --- GET /admin/corporates/{id} ---------------------------------------------


def test_get_corporate_returns_full_row():
    corp = _corporate()
    session = _session_with_corporate(corp)

    res = _client(session).get(f"/admin/corporates/{corp.id}")

    assert res.status_code == 200
    body = res.json()
    assert body["id"] == str(corp.id)
    assert body["primary_color"] == "#7C3AED"
    assert body["contact_phone"] == "+1 555 0100"
    assert body["allowed_hr_emails"] == ["hr@acme.example"]


def test_get_corporate_unknown_is_404():
    session = _session_with_corporate(None)

    res = _client(session).get(f"/admin/corporates/{uuid4()}")

    assert res.status_code == 404


def test_get_corporate_rejects_non_ops_user():
    session = AsyncMock()

    res = _client(session, ops=False).get(f"/admin/corporates/{uuid4()}")

    assert res.status_code == 403
    session.execute.assert_not_called()


# --- PATCH /admin/corporates/{id} -------------------------------------------


def test_update_corporate_sets_provided_fields_and_clears_blanks():
    corp = _corporate()
    session = _session_with_corporate(corp)

    res = _client(session).patch(
        f"/admin/corporates/{corp.id}",
        json={"primary_color": "#112233", "contact_phone": "", "logo_url": None},
    )

    assert res.status_code == 200
    assert corp.primary_color == "#112233"
    assert corp.contact_phone is None
    assert corp.logo_url is None
    # Omitted fields are untouched.
    assert corp.contact_email == "hr@acme.example"
    session.commit.assert_awaited_once()
    body = res.json()
    assert body["primary_color"] == "#112233"
    assert body["contact_phone"] is None


def test_update_corporate_rejects_unknown_fields():
    corp = _corporate()
    session = _session_with_corporate(corp)

    res = _client(session).patch(
        f"/admin/corporates/{corp.id}", json={"allowed_hr_emails": ["x@evil.example"]}
    )

    assert res.status_code == 422
    session.commit.assert_not_called()


def test_update_corporate_unknown_is_404():
    session = _session_with_corporate(None)

    res = _client(session).patch(f"/admin/corporates/{uuid4()}", json={"primary_color": "#000000"})

    assert res.status_code == 404
    session.commit.assert_not_called()


def test_update_corporate_rejects_non_ops_user():
    session = AsyncMock()

    res = _client(session, ops=False).patch(
        f"/admin/corporates/{uuid4()}", json={"primary_color": "#000000"}
    )

    assert res.status_code == 403
    session.execute.assert_not_called()
