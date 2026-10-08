"""Tests for GET /api/v1/admin/candidates/{id}/report tenant gating."""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.v1.reports import router
from app.auth import HRUserContext, get_current_hr_user
from app.database import get_db


@pytest.fixture
def home_corp():
    return uuid4()


@pytest.fixture
def candidate_id():
    return uuid4()


def _app(hr: HRUserContext) -> FastAPI:
    application = FastAPI()
    application.include_router(router, prefix="/api/v1/admin/candidates")

    async def _hr():
        return hr

    async def _db():
        yield AsyncMock()

    application.dependency_overrides[get_current_hr_user] = _hr
    application.dependency_overrides[get_db] = _db
    return application


def test_report_forbids_hr_other_tenant(home_corp, candidate_id):
    hr = HRUserContext(
        user_id=uuid4(), corporate_id=home_corp, email="hr@test.com", role="hr"
    )
    other = uuid4()
    candidate = SimpleNamespace(
        id=candidate_id, corporate_id=other, package_id=uuid4()
    )
    app = _app(hr)
    with patch(
        "app.api.v1.reports.CandidateService.get_candidate",
        new=AsyncMock(return_value=candidate),
    ):
        res = TestClient(app).get(f"/api/v1/admin/candidates/{candidate_id}/report")
    assert res.status_code == 403


def test_report_allows_ops_other_tenant(home_corp, candidate_id):
    hr = HRUserContext(
        user_id=uuid4(), corporate_id=home_corp, email="ops@test.com", role="admin"
    )
    other = uuid4()
    package_id = uuid4()
    candidate = SimpleNamespace(
        id=candidate_id,
        corporate_id=other,
        package_id=package_id,
        full_name="Pat",
        email="pat@ex.com",
    )
    package = SimpleNamespace(id=package_id, title="Pack")
    app = _app(hr)

    async def _empty_execute(*_args, **_kwargs):
        result = SimpleNamespace()
        result.scalar_one_or_none = lambda: None
        result.scalars = lambda: SimpleNamespace(all=lambda: [])
        return result

    db = AsyncMock()
    db.execute = AsyncMock(side_effect=_empty_execute)

    async def _db():
        yield db

    app.dependency_overrides[get_db] = _db

    with (
        patch(
            "app.api.v1.reports.CandidateService.get_candidate",
            new=AsyncMock(return_value=candidate),
        ),
        patch(
            "app.api.v1.reports.PackageService.get_package",
            new=AsyncMock(return_value=package),
        ),
        patch(
            "app.api.v1.reports.JdScoringService.get_or_evaluate",
            new=AsyncMock(return_value=(None, "skipped")),
        ),
        patch(
            "app.api.v1.reports.ReportService.generate_report_bytes",
            return_value=(b"<html>ok</html>", False),
        ),
        patch("app.api.v1.reports.storage_service.upload_report", return_value=None),
    ):
        res = TestClient(app).get(f"/api/v1/admin/candidates/{candidate_id}/report")
    assert res.status_code == 200
    assert res.content == b"<html>ok</html>"
