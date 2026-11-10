"""POST /api/v1/admin/candidates/{id}/reset — wipe progress for retake."""
from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.v1.notifications import router as notifications_router
from app.auth import HRUserContext, get_current_hr_user
from app.database import get_db
from app.services.candidate_service import CandidateService, NOT_STARTED_STATUS


def _app(*, corporate_id, role: str = "hr") -> TestClient:
    application = FastAPI()
    application.include_router(notifications_router, prefix="/api/v1/admin/candidates")

    async def _db():
        yield AsyncMock()

    async def _hr():
        return HRUserContext(
            user_id=uuid4(),
            corporate_id=corporate_id,
            email="user@t.com",
            role=role,
        )

    application.dependency_overrides[get_db] = _db
    application.dependency_overrides[get_current_hr_user] = _hr
    return TestClient(application)


def _candidate(*, corporate_id, logged_in: bool = True):
    return SimpleNamespace(
        id=uuid4(),
        corporate_id=corporate_id,
        package_id=uuid4(),
        full_name="Ada Lovelace",
        email="ada@example.com",
        access_code="ABC-123",
        logged_in_at=datetime.now(timezone.utc) if logged_in else None,
    )


def test_reset_returns_404_when_candidate_missing():
    corp = uuid4()
    with patch.object(CandidateService, "get_candidate", new=AsyncMock(return_value=None)):
        res = _app(corporate_id=corp).post(f"/api/v1/admin/candidates/{uuid4()}/reset")

    assert res.status_code == 404
    assert res.json() == {"detail": "Candidate not found"}


def test_reset_forbidden_for_cross_tenant_hr():
    caller_corp = uuid4()
    candidate = _candidate(corporate_id=uuid4())
    reset = AsyncMock()
    purge = MagicMock()

    with (
        patch.object(CandidateService, "get_candidate", new=AsyncMock(return_value=candidate)),
        patch.object(CandidateService, "reset_assessment", new=reset),
        patch("app.api.v1.notifications.storage_service.purge_cached_reports", new=purge),
    ):
        res = _app(corporate_id=caller_corp, role="hr").post(
            f"/api/v1/admin/candidates/{candidate.id}/reset"
        )

    assert res.status_code == 403
    assert res.json() == {"detail": "Forbidden"}
    reset.assert_not_awaited()
    purge.assert_not_called()


def test_reset_allows_ops_cross_tenant_and_purges_cache():
    caller_corp = uuid4()
    candidate = _candidate(corporate_id=uuid4())
    reset = AsyncMock(return_value=candidate)
    purge = MagicMock(return_value=2)

    with (
        patch.object(CandidateService, "get_candidate", new=AsyncMock(return_value=candidate)),
        patch.object(CandidateService, "reset_assessment", new=reset),
        patch("app.api.v1.notifications.storage_service.purge_cached_reports", new=purge),
    ):
        res = _app(corporate_id=caller_corp, role="admin").post(
            f"/api/v1/admin/candidates/{candidate.id}/reset"
        )

    assert res.status_code == 200
    assert res.json() == {
        "success": True,
        "message": "Candidate assessment successfully reset",
    }
    reset.assert_awaited_once()
    purge.assert_called_once_with(candidate.corporate_id, candidate.id)


@pytest.mark.asyncio
async def test_reset_assessment_clears_child_rows_and_login():
    candidate = _candidate(corporate_id=uuid4(), logged_in=True)
    session = AsyncMock()
    session.execute = AsyncMock()
    session.commit = AsyncMock()
    session.refresh = AsyncMock()

    result = await CandidateService.reset_assessment(session, candidate)

    assert result is candidate
    assert candidate.logged_in_at is None
    assert session.execute.await_count == 3
    session.commit.assert_awaited_once()
    session.refresh.assert_awaited_once_with(candidate)

    # Progress UPDATE must reset to NOT_STARTED (compile values for sanity).
    progress_stmt = session.execute.await_args_list[1].args[0]
    compiled = progress_stmt.compile()
    assert compiled.params.get("status") == NOT_STARTED_STATUS or NOT_STARTED_STATUS in str(
        progress_stmt
    )
