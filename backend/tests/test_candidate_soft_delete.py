"""POST /api/v1/admin/candidates/{id}/soft-delete — hide candidate from active lists."""
from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.v1.notifications import router as notifications_router
from app.auth import HRUserContext, get_current_hr_user
from app.database import get_db
from app.services.candidate_service import CandidateService


def _app(*, corporate_id, role: str = "admin", user_id=None) -> TestClient:
    application = FastAPI()
    application.include_router(notifications_router, prefix="/api/v1/admin/candidates")
    actor = user_id or uuid4()

    async def _db():
        yield AsyncMock()

    async def _hr():
        return HRUserContext(
            user_id=actor,
            corporate_id=corporate_id,
            email="ops@t.com",
            role=role,
        )

    application.dependency_overrides[get_db] = _db
    application.dependency_overrides[get_current_hr_user] = _hr
    return TestClient(application)


def _candidate(*, corporate_id, deleted: bool = False):
    return SimpleNamespace(
        id=uuid4(),
        corporate_id=corporate_id,
        package_id=uuid4(),
        full_name="Ada Lovelace",
        email="ada@example.com",
        access_code="ABC-123",
        logged_in_at=datetime.now(timezone.utc),
        deleted_at=datetime.now(timezone.utc) if deleted else None,
    )


def test_soft_delete_returns_404_when_candidate_missing():
    corp = uuid4()
    with patch.object(CandidateService, "get_candidate", new=AsyncMock(return_value=None)):
        res = _app(corporate_id=corp).post(f"/api/v1/admin/candidates/{uuid4()}/soft-delete")

    assert res.status_code == 404
    assert res.json() == {"detail": "Candidate not found"}


def test_soft_delete_forbidden_for_hr():
    corp = uuid4()
    candidate = _candidate(corporate_id=corp)
    soft = AsyncMock()

    with (
        patch.object(CandidateService, "get_candidate", new=AsyncMock(return_value=candidate)),
        patch.object(CandidateService, "soft_delete_candidate", new=soft),
    ):
        res = _app(corporate_id=corp, role="hr").post(
            f"/api/v1/admin/candidates/{candidate.id}/soft-delete"
        )

    assert res.status_code == 403
    assert res.json() == {"detail": "Forbidden"}
    soft.assert_not_awaited()


def test_soft_delete_allows_ops():
    corp = uuid4()
    candidate = _candidate(corporate_id=corp)
    soft = AsyncMock(return_value=candidate)

    with (
        patch.object(CandidateService, "get_candidate", new=AsyncMock(return_value=candidate)),
        patch.object(CandidateService, "soft_delete_candidate", new=soft),
    ):
        res = _app(corporate_id=corp, role="admin").post(
            f"/api/v1/admin/candidates/{candidate.id}/soft-delete"
        )

    assert res.status_code == 200
    assert res.json() == {
        "success": True,
        "message": "Candidate successfully deleted",
    }
    soft.assert_awaited_once()


@pytest.mark.asyncio
async def test_soft_delete_sets_deleted_at():
    candidate = _candidate(corporate_id=uuid4())
    session = AsyncMock()
    session.commit = AsyncMock()
    session.refresh = AsyncMock()
    admin_id = uuid4()

    result = await CandidateService.soft_delete_candidate(
        session, candidate, admin_user_id=admin_id
    )

    assert result is candidate
    assert candidate.deleted_at is not None
    session.commit.assert_awaited_once()
    session.refresh.assert_awaited_once_with(candidate)
