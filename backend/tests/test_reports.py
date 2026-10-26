"""Tests for GET /api/v1/admin/candidates/{id}/report tenant gating."""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.v1.reports import report_content_disposition, router
from app.auth import HRUserContext, get_current_hr_user
from app.database import get_db
from app.schemas.mindq_report import MindQReportResponse


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


@pytest.mark.parametrize(
    ("name", "ascii_part", "utf8_part"),
    [
        ("Jane Doe", 'filename="MindQ Report - Jane Doe.pdf"', "MindQ%20Report%20-%20Jane%20Doe.pdf"),
        ('A/B"C\r\nD', 'filename="MindQ Report - A B C D.pdf"', "A%20B%20C%20D.pdf"),
        ("நிலா", 'filename="MindQ Report - Candidate.pdf"', "%E0%AE%A8"),
        ("   ", 'filename="MindQ Report - Candidate.pdf"', "Candidate.pdf"),
    ],
)
def test_report_content_disposition(name, ascii_part, utf8_part):
    header = report_content_disposition(name, "pdf")
    assert ascii_part in header
    assert "filename*=UTF-8''" in header and utf8_part in header
    assert "\r" not in header and "\n" not in header


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
    report = MindQReportResponse(
        candidate_id=candidate_id,
        company_name="Acme",
        candidate_full_name="Pat",
        candidate_email="pat@ex.com",
        target_role="Analyst",
        total_assessments_completed=0,
        category_averages={},
        executive_summary="",
        competency_breakdown=[],
        synthesis_status="skipped",
    )
    app = _app(hr)
    generate = MagicMock(return_value=(b"<html>ok</html>", False))

    with (
        patch(
            "app.api.v1.reports.CandidateService.get_candidate",
            new=AsyncMock(return_value=candidate),
        ),
        patch(
            "app.api.v1.reports.build_technical_report_data",
            new=AsyncMock(return_value=report),
        ),
        patch("app.api.v1.reports.ReportService.generate_report_bytes", new=generate),
        patch("app.api.v1.reports.storage_service.upload_report", return_value=None),
    ):
        res = TestClient(app).get(f"/api/v1/admin/candidates/{candidate_id}/report")
    assert res.status_code == 200
    assert res.content == b"<html>ok</html>"
    assert res.headers["X-Report-Synthesis-Status"] == "skipped"
    assert 'filename="MindQ Report - Pat.html"' in res.headers["Content-Disposition"]
    rendered = generate.call_args.kwargs["report"]
    assert rendered["candidate_full_name"] == "Pat"
    assert "overall_fit" not in rendered
