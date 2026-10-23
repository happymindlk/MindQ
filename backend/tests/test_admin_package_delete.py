"""Ops DELETE /admin/packages/{id}: soft-archive published, hard-delete drafts."""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.v1.admin_ops import router as admin_router
from app.auth import HRUserContext, get_current_ops_user
from app.database import get_db
from app.services.package_share import display_status


def _client(session: AsyncMock) -> TestClient:
    application = FastAPI()
    application.include_router(admin_router, prefix="/admin")

    async def _db():
        yield session

    async def _ops():
        return HRUserContext(user_id=uuid4(), corporate_id=uuid4(), role="admin")

    application.dependency_overrides[get_db] = _db
    application.dependency_overrides[get_current_ops_user] = _ops
    return TestClient(application)


def _package(*, status: str = "published", is_active: bool = True):
    return SimpleNamespace(
        id=uuid4(),
        status=status,
        is_active=is_active,
        title="Suite",
    )


def _session_with_package(package):
    result = MagicMock()
    result.scalar_one_or_none.return_value = package
    session = AsyncMock()
    session.execute = AsyncMock(return_value=result)
    session.commit = AsyncMock()
    session.refresh = AsyncMock()
    session.delete = AsyncMock()
    return session


def test_display_status_keeps_inactive_drafts_as_draft():
    draft = _package(status="draft", is_active=False)
    assert display_status(draft) == "draft"
    published = _package(status="published", is_active=True)
    assert display_status(published) == "published"
    archived = _package(status="published", is_active=False)
    assert display_status(archived) == "archived"


def test_soft_delete_published_package_marks_inactive():
    pkg = _package(status="published", is_active=True)
    session = _session_with_package(pkg)

    res = _client(session).delete(f"/admin/packages/{pkg.id}")

    assert res.status_code == 200
    assert res.json() == {"id": str(pkg.id), "status": "archived"}
    assert pkg.is_active is False
    session.commit.assert_awaited_once()
    session.delete.assert_not_called()


def test_delete_draft_package_hard_deletes():
    pkg = _package(status="draft", is_active=False)
    session = _session_with_package(pkg)

    res = _client(session).delete(f"/admin/packages/{pkg.id}")

    assert res.status_code == 200
    assert res.json() == {"id": str(pkg.id), "status": "deleted"}
    assert session.execute.await_count >= 2
    session.commit.assert_awaited_once()


def test_delete_missing_or_archived_package_returns_404():
    missing = _session_with_package(None)
    res_missing = _client(missing).delete(f"/admin/packages/{uuid4()}")
    assert res_missing.status_code == 404
    missing.commit.assert_not_called()

    archived = _package(status="published", is_active=False)
    session = _session_with_package(archived)
    res_archived = _client(session).delete(f"/admin/packages/{archived.id}")
    assert res_archived.status_code == 404
    session.commit.assert_not_called()
