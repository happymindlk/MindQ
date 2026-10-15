"""Client pipeline/scorecard/dashboard map schema-drift DB errors to an actionable 503."""
from __future__ import annotations

from unittest.mock import AsyncMock, patch
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.exc import ProgrammingError

from app.api.v1.client import router as client_router
from app.auth import ClientUserContext, get_current_client_user
from app.database import get_db
from app.exceptions import schema_drift_detail


def _client() -> TestClient:
    application = FastAPI()
    application.include_router(client_router, prefix="/client")

    async def _db():
        yield AsyncMock()

    async def _client_user():
        return ClientUserContext(user_id=uuid4(), corporate_id=uuid4())

    application.dependency_overrides[get_db] = _db
    application.dependency_overrides[get_current_client_user] = _client_user
    return TestClient(application)


def _undefined_column() -> ProgrammingError:
    return ProgrammingError(
        "SELECT packages.allow_open_enrollment FROM packages",
        {},
        Exception('column packages.allow_open_enrollment does not exist'),
    )


def test_pipeline_schema_drift_returns_503_with_migration_hint():
    async def _boom(_session, _corporate_id):
        raise _undefined_column()

    with patch(
        "app.api.v1.client.ClientPackageService.list_client_pipeline", new=_boom
    ):
        res = _client().get("/client/pipeline")

    assert res.status_code == 503
    assert "migration" in res.json()["detail"].lower()
    assert "allow_open_enrollment" not in res.json()["detail"]


def test_scorecard_schema_drift_returns_503():
    async def _boom(_session, _candidate_id, _corporate_id):
        raise _undefined_column()

    with patch(
        "app.api.v1.client.ClientPackageService.get_client_scorecard", new=_boom
    ):
        res = _client().get(f"/client/candidates/{uuid4()}/scorecard")

    assert res.status_code == 503


def test_dashboard_schema_drift_returns_503():
    async def _boom(_session, _corporate_id):
        raise _undefined_column()

    with patch(
        "app.api.v1.client.ClientPackageService.get_client_dashboard", new=_boom
    ):
        res = _client().get("/client/dashboard")

    assert res.status_code == 503
    assert "migration" in res.json()["detail"].lower()


def test_schema_drift_detail_does_not_echo_unrelated_driver_errors():
    exc = ProgrammingError("SELECT 1", {}, Exception("syntax error at or near FROM"))
    assert schema_drift_detail(exc) == "Database query failed"
