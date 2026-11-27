"""Tenant isolation: Corporate A's HR must never read Corporate B's data.

Architecture note (audit):
  The FastAPI backend connects via ``DATABASE_URL`` as the Postgres role
  (local default ``postgres`` / hosted pooler equivalent). That role bypasses
  Supabase RLS the same way ``service_role`` does for Storage/Auth Admin APIs
  (``SUPABASE_SERVICE_ROLE_KEY``). Tenant isolation is therefore enforced in
  application code: every HR/client query must filter on
  ``corporate_id == current_user.corporate_id`` (or reject after load).

  Frontend supabase-js paths are covered separately by ``scripts/verify_rls.sh``
  + ``supabase/tests/rls_assertions.sql`` in CI. This suite covers every
  FastAPI endpoint that returns tenant-scoped packages, candidates, results,
  or reports — including report file / cache paths keyed by corporate_id.
"""
from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.v1 import client as client_module
from app.api.v1.candidate_reports import router as candidate_reports_router
from app.api.v1.client import router as client_router
from app.api.v1.corporates import router as corporates_router
from app.api.v1.notifications import router as notifications_router
from app.api.v1.reports import router as admin_reports_router
from app.auth import ClientUserContext, HRUserContext, get_current_client_user, get_current_hr_user
from app.config import settings
from app.database import get_db
from app.schemas.client_package import (
    ClientCorporate,
    ClientDashboardPackage,
    ClientDashboardResponse,
    ClientPipelineRow,
)
from app.schemas.mindq_report import MindQReportResponse
from app.security import RateLimiter
from app.services import storage as storage_service
from app.services.client_package import ClientPackageService


# ---------------------------------------------------------------------------
# Shared fixtures: two tenants with packages, candidates, and report ids
# ---------------------------------------------------------------------------


@pytest.fixture
def tenant_a() -> SimpleNamespace:
    corp = uuid4()
    package = uuid4()
    candidate = uuid4()
    return SimpleNamespace(
        corporate_id=corp,
        package_id=package,
        candidate_id=candidate,
        candidate=SimpleNamespace(
            id=candidate,
            corporate_id=corp,
            package_id=package,
            full_name="Ada A",
            email="ada@a.test",
            access_code="AAAAAA",
            logged_in_at=None,
            created_at=datetime.now(timezone.utc),
        ),
        package=SimpleNamespace(
            id=package,
            title="Corp A Role",
            corporate_id=corp,
            status="published",
            is_active=True,
        ),
    )


@pytest.fixture
def tenant_b() -> SimpleNamespace:
    corp = uuid4()
    package = uuid4()
    candidate = uuid4()
    return SimpleNamespace(
        corporate_id=corp,
        package_id=package,
        candidate_id=candidate,
        candidate=SimpleNamespace(
            id=candidate,
            corporate_id=corp,
            package_id=package,
            full_name="Bob B",
            email="bob@b.test",
            access_code="BBBBBB",
            logged_in_at=None,
            created_at=datetime.now(timezone.utc),
        ),
        package=SimpleNamespace(
            id=package,
            title="Corp B Role",
            corporate_id=corp,
            status="published",
            is_active=True,
        ),
    )


@pytest.fixture(autouse=True)
def _fresh_client_limiters(monkeypatch):
    monkeypatch.setattr(client_module, "report_limiter", RateLimiter(50, 600))
    monkeypatch.setattr(client_module, "report_view_limiter", RateLimiter(50, 600))
    monkeypatch.setattr(client_module, "reports_zip_limiter", RateLimiter(20, 600))


def _scalar(value):
    res = MagicMock()
    res.scalar_one_or_none.return_value = value
    return res


def _scalars(values: list):
    res = MagicMock()
    res.scalars.return_value.all.return_value = values
    return res


def _mindq(candidate_id: UUID, name: str = "Pat") -> MindQReportResponse:
    return MindQReportResponse(
        candidate_id=candidate_id,
        company_name="Acme",
        candidate_full_name=name,
        candidate_email="pat@ex.com",
        target_role="Analyst",
        total_assessments_completed=1,
        executive_summary="Solid fundamentals.",
        synthesis_status="ok",
    )


def _client_app(corporate_id: UUID, db: AsyncMock | None = None) -> TestClient:
    application = FastAPI()
    application.include_router(client_router, prefix="/api/v1/client")

    async def _db():
        yield db or AsyncMock()

    async def _user():
        return ClientUserContext(user_id=uuid4(), corporate_id=corporate_id, email="hr@a.test")

    application.dependency_overrides[get_db] = _db
    application.dependency_overrides[get_current_client_user] = _user
    return TestClient(application)


def _hr_app(
    corporate_id: UUID,
    *,
    include_reports: bool = True,
    include_candidate_reports: bool = True,
    include_notifications: bool = True,
    include_corporates: bool = True,
    db: AsyncMock | None = None,
) -> TestClient:
    application = FastAPI()
    if include_reports:
        application.include_router(admin_reports_router, prefix="/api/v1/admin/candidates")
    if include_candidate_reports:
        application.include_router(candidate_reports_router, prefix="/api/v1/candidates")
    if include_notifications:
        application.include_router(notifications_router, prefix="/api/v1/admin/candidates")
    if include_corporates:
        application.include_router(corporates_router, prefix="/api/v1/corporates")

    async def _db():
        yield db or AsyncMock()

    async def _hr():
        return HRUserContext(
            user_id=uuid4(),
            corporate_id=corporate_id,
            email="hr@a.test",
            role="hr",
        )

    application.dependency_overrides[get_db] = _db
    application.dependency_overrides[get_current_hr_user] = _hr
    return TestClient(application)


# ---------------------------------------------------------------------------
# Connection / trust-boundary audit
# ---------------------------------------------------------------------------


def test_backend_database_url_uses_privileged_role_not_rls_jwt():
    """FastAPI talks to Postgres directly; RLS is not the API trust boundary."""
    url = settings.DATABASE_URL
    assert "postgresql" in url
    # Default / documented connection is the postgres (or pooler) role — not an
    # RLS-constrained ``authenticated`` JWT session. App code must scope tenants.
    assert "authenticated" not in url.lower()
    assert settings.SUPABASE_SERVICE_ROLE_KEY is not None  # may be blank in unit CI


def test_report_object_keys_are_tenant_prefixed(tenant_a, tenant_b):
    """Report archive / cache paths always start with the owning corporate_id."""
    a_key = storage_service._report_key(tenant_a.corporate_id, tenant_a.candidate_id, True)
    b_key = storage_service._report_key(tenant_b.corporate_id, tenant_b.candidate_id, True)
    assert a_key.startswith(f"{tenant_a.corporate_id}/")
    assert b_key.startswith(f"{tenant_b.corporate_id}/")
    assert a_key != b_key
    # Cross-tenant candidate id under wrong prefix is a different object.
    swapped = storage_service._report_key(tenant_a.corporate_id, tenant_b.candidate_id, True)
    assert swapped.startswith(f"{tenant_a.corporate_id}/")
    assert not swapped.startswith(f"{tenant_b.corporate_id}/")


def test_cached_report_prefix_isolates_tenants(tenant_a, tenant_b):
    digest = "a" * 64
    a = storage_service._cached_report_key(
        tenant_a.corporate_id, tenant_a.candidate_id, digest
    )
    b = storage_service._cached_report_key(
        tenant_b.corporate_id, tenant_b.candidate_id, digest
    )
    assert a.startswith(f"{tenant_a.corporate_id}/{tenant_a.candidate_id}/")
    assert b.startswith(f"{tenant_b.corporate_id}/{tenant_b.candidate_id}/")
    assert a != b


def test_presigned_report_url_uses_caller_corporate_prefix(tenant_a, tenant_b, monkeypatch):
    """Presign must target the verified corporate_id prefix — never another tenant's key."""
    seen: dict = {}

    class _FakeS3:
        def generate_presigned_url(self, *_args, **kwargs):
            seen["params"] = kwargs["Params"]
            return "https://storage.test/presigned"

    monkeypatch.setattr(storage_service.settings, "R2_REPORTS_BUCKET_NAME", "private-reports")
    monkeypatch.setattr(storage_service, "_reports_bucket_safe", lambda: True)
    monkeypatch.setattr(storage_service, "_s3_client", lambda: _FakeS3())

    url = storage_service.get_report_download_url(
        tenant_a.corporate_id, tenant_b.candidate_id, is_pdf=True
    )
    assert url == "https://storage.test/presigned"
    key = seen["params"]["Key"]
    assert key == f"{tenant_a.corporate_id}/{tenant_b.candidate_id}.pdf"
    assert str(tenant_b.corporate_id) not in key


# ---------------------------------------------------------------------------
# Client portal (client_hr JWT) — packages / candidates / reports
# ---------------------------------------------------------------------------


def test_client_dashboard_scopes_to_token_corporate_only(tenant_a, tenant_b):
    seen: dict = {}

    async def _dashboard(_session, corporate_id: UUID):
        seen["corporate_id"] = corporate_id
        return ClientDashboardResponse(
            corporate=ClientCorporate(id=corporate_id, name="A"),
            packages=[
                ClientDashboardPackage(
                    id=tenant_a.package_id,
                    title="Corp A Role",
                    access_code="AAAAAA",
                    candidate_path="/portal?code=AAAAAA",
                    total_invited=1,
                    total_completed=0,
                    candidates=[],
                )
            ],
        )

    with patch(
        "app.api.v1.client.ClientPackageService.get_client_dashboard", new=_dashboard
    ):
        res = _client_app(tenant_a.corporate_id).get("/api/v1/client/dashboard")

    assert res.status_code == 200
    assert seen["corporate_id"] == tenant_a.corporate_id
    assert seen["corporate_id"] != tenant_b.corporate_id
    body = res.json()
    assert body["corporate"]["id"] == str(tenant_a.corporate_id)
    assert all(p["id"] == str(tenant_a.package_id) for p in body["packages"])


@pytest.mark.parametrize("path", ["/api/v1/client/pipeline", "/api/v1/client/candidates"])
def test_client_pipeline_scopes_to_token_corporate_only(path, tenant_a, tenant_b):
    seen: dict = {}

    async def _pipeline(_session, corporate_id: UUID):
        seen["corporate_id"] = corporate_id
        return [
            ClientPipelineRow(
                id=tenant_a.candidate_id,
                package_id=tenant_a.package_id,
                package_title="Corp A Role",
                full_name="Ada A",
                email="ada@a.test",
                pipeline_status="Completed",
                completed_assessments=1,
                total_assessments=1,
                created_at=datetime.now(timezone.utc),
            )
        ]

    with patch(
        "app.api.v1.client.ClientPackageService.list_client_pipeline", new=_pipeline
    ):
        res = _client_app(tenant_a.corporate_id).get(path)

    assert res.status_code == 200
    assert seen["corporate_id"] == tenant_a.corporate_id
    rows = res.json()
    assert len(rows) == 1
    assert rows[0]["id"] == str(tenant_a.candidate_id)
    assert rows[0]["id"] != str(tenant_b.candidate_id)


def test_client_scorecard_404_for_other_tenant(tenant_a, tenant_b):
    scorecard = AsyncMock(side_effect=LookupError("Candidate not found"))
    with patch(
        "app.api.v1.client.ClientPackageService.get_client_scorecard", new=scorecard
    ):
        res = _client_app(tenant_a.corporate_id).get(
            f"/api/v1/client/candidates/{tenant_b.candidate_id}/scorecard"
        )
    assert res.status_code == 404
    assert res.json() == {"detail": "Candidate not found"}
    assert scorecard.await_args.args[1] == tenant_b.candidate_id
    assert scorecard.await_args.args[2] == tenant_a.corporate_id


def test_client_report_data_404_for_other_tenant(tenant_a, tenant_b):
    db = AsyncMock()
    db.execute.return_value = _scalar(None)
    build = AsyncMock()
    with patch("app.api.v1.client.build_technical_report_data", new=build):
        res = _client_app(tenant_a.corporate_id, db).get(
            f"/api/v1/client/candidates/{tenant_b.candidate_id}/report-data"
        )
    assert res.status_code == 404
    build.assert_not_awaited()


def test_client_report_pdf_404_never_hits_storage(tenant_a, tenant_b):
    db = AsyncMock()
    db.execute.return_value = _scalar(None)
    build = AsyncMock()
    fetch = MagicMock()
    with (
        patch("app.api.v1.client.build_technical_report_data", new=build),
        patch("app.services.report_pdf.storage_service.fetch_cached_report", new=fetch),
    ):
        res = _client_app(tenant_a.corporate_id, db).get(
            f"/api/v1/client/candidates/{tenant_b.candidate_id}/report"
        )
    assert res.status_code == 404
    build.assert_not_awaited()
    fetch.assert_not_called()


def test_client_package_reports_zip_404_for_other_tenant(tenant_a, tenant_b):
    lookup = AsyncMock(side_effect=LookupError("Package not found"))
    with patch(
        "app.api.v1.client.ClientPackageService.get_package_completed_candidates",
        new=lookup,
    ):
        res = _client_app(tenant_a.corporate_id).get(
            f"/api/v1/client/packages/{tenant_b.package_id}/reports-zip"
        )
    assert res.status_code == 404
    assert lookup.await_args.args[1] == tenant_b.package_id
    assert lookup.await_args.args[2] == tenant_a.corporate_id


def test_client_own_candidate_report_uses_own_storage_prefix(tenant_a):
    """Authorized PDF download keys storage with the candidate's corporate_id."""
    from fastapi.responses import Response

    db = AsyncMock()
    db.execute.return_value = _scalar(tenant_a.candidate)
    report = _mindq(tenant_a.candidate_id, "Ada A")

    async def _serve(*_a, **kwargs):
        assert kwargs["corporate_id"] == tenant_a.corporate_id
        assert kwargs["candidate_id"] == tenant_a.candidate_id
        return Response(content=b"%PDF-1.7", media_type="application/pdf")

    with (
        patch(
            "app.api.v1.client.build_technical_report_data",
            new=AsyncMock(return_value=report),
        ),
        patch("app.api.v1.client.serve_report_pdf", new=_serve),
    ):
        res = _client_app(tenant_a.corporate_id, db).get(
            f"/api/v1/client/candidates/{tenant_a.candidate_id}/report"
        )
    assert res.status_code == 200
    assert res.content == b"%PDF-1.7"


# ---------------------------------------------------------------------------
# Admin / HR Supabase JWT routes — results & reports
# ---------------------------------------------------------------------------


def test_hr_report_data_403_for_other_tenant(tenant_a, tenant_b):
    db = AsyncMock()
    db.execute.return_value = _scalar(tenant_b.candidate)
    build = AsyncMock()
    with patch("app.api.v1.candidate_reports.build_technical_report_data", new=build):
        res = _hr_app(
            tenant_a.corporate_id,
            include_reports=False,
            include_notifications=False,
            include_corporates=False,
            db=db,
        ).get(f"/api/v1/candidates/{tenant_b.candidate_id}/report-data")
    assert res.status_code == 403
    build.assert_not_awaited()


def test_hr_admin_report_pdf_403_for_other_tenant(tenant_a, tenant_b):
    build = AsyncMock()
    with (
        patch(
            "app.api.v1.reports.CandidateService.get_candidate",
            new=AsyncMock(return_value=tenant_b.candidate),
        ),
        patch("app.api.v1.reports.build_technical_report_data", new=build),
    ):
        res = _hr_app(
            tenant_a.corporate_id,
            include_candidate_reports=False,
            include_notifications=False,
            include_corporates=False,
        ).get(f"/api/v1/admin/candidates/{tenant_b.candidate_id}/report")
    assert res.status_code == 403
    build.assert_not_awaited()


def test_hr_nudge_403_for_other_tenant(tenant_a, tenant_b):
    with patch(
        "app.api.v1.notifications.CandidateService.get_candidate",
        new=AsyncMock(return_value=tenant_b.candidate),
    ):
        res = _hr_app(
            tenant_a.corporate_id,
            include_reports=False,
            include_candidate_reports=False,
            include_corporates=False,
        ).post(f"/api/v1/admin/candidates/{tenant_b.candidate_id}/nudge")
    assert res.status_code == 403


def test_hr_reset_403_for_other_tenant(tenant_a, tenant_b):
    reset = AsyncMock()
    purge = MagicMock()
    with (
        patch(
            "app.api.v1.notifications.CandidateService.get_candidate",
            new=AsyncMock(return_value=tenant_b.candidate),
        ),
        patch("app.api.v1.notifications.CandidateService.reset_assessment", new=reset),
        patch("app.api.v1.notifications.storage_service.purge_cached_reports", new=purge),
    ):
        res = _hr_app(
            tenant_a.corporate_id,
            include_reports=False,
            include_candidate_reports=False,
            include_corporates=False,
        ).post(f"/api/v1/admin/candidates/{tenant_b.candidate_id}/reset")
    assert res.status_code == 403
    reset.assert_not_awaited()
    purge.assert_not_called()


def test_hr_logo_upload_403_for_other_tenant(tenant_a, tenant_b):
    res = _hr_app(
        tenant_a.corporate_id,
        include_reports=False,
        include_candidate_reports=False,
        include_notifications=False,
    ).post(
        f"/api/v1/corporates/{tenant_b.corporate_id}/logo",
        files={"file": ("logo.png", b"\x89PNG\r\n\x1a\n", "image/png")},
    )
    assert res.status_code == 403


# ---------------------------------------------------------------------------
# Service-layer SQL: every list/get path includes corporate_id
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_client_pipeline_sql_filters_corporate(tenant_a, tenant_b):
    db = AsyncMock()
    db.execute.side_effect = [
        _scalars([tenant_a.candidate]),
        _scalars([tenant_a.package]),
        _scalars([]),  # assessments aggregate path may vary — keep empty
        MagicMock(all=MagicMock(return_value=[])),
        MagicMock(all=MagicMock(return_value=[])),
        MagicMock(all=MagicMock(return_value=[])),
        MagicMock(all=MagicMock(return_value=[])),
        _scalars([]),
    ]
    # Prefer asserting the WHERE clause on the first (candidates) query.
    with patch(
        "app.services.client_package._candidate_aggregates",
        new=AsyncMock(
            return_value=SimpleNamespace(
                total_for=lambda c: 1,
                completed={},
                evaluated=set(),
                avg_score={},
                completed_at={},
            )
        ),
    ):
        rows = await ClientPackageService.list_client_pipeline(db, tenant_a.corporate_id)

    assert len(rows) == 1
    assert rows[0].id == tenant_a.candidate_id
    cand_stmt = str(db.execute.await_args_list[0].args[0])
    assert "candidates.corporate_id" in cand_stmt
    params = db.execute.await_args_list[0].args[0].compile().params
    assert tenant_a.corporate_id in params.values()
    assert tenant_b.corporate_id not in params.values()


@pytest.mark.asyncio
async def test_get_package_completed_candidates_rejects_other_tenant(tenant_a, tenant_b):
    db = AsyncMock()
    db.execute.return_value = _scalar(None)
    with pytest.raises(LookupError, match="Package not found"):
        await ClientPackageService.get_package_completed_candidates(
            db, tenant_b.package_id, tenant_a.corporate_id
        )
    stmt = str(db.execute.await_args.args[0])
    assert "packages.corporate_id" in stmt
    params = db.execute.await_args.args[0].compile().params
    assert tenant_a.corporate_id in params.values()


@pytest.mark.asyncio
async def test_get_client_scorecard_rejects_other_tenant(tenant_a, tenant_b):
    db = AsyncMock()
    db.execute.return_value = _scalar(None)
    with pytest.raises(LookupError, match="Candidate not found"):
        await ClientPackageService.get_client_scorecard(
            db, tenant_b.candidate_id, tenant_a.corporate_id
        )
    stmt = str(db.execute.await_args.args[0])
    assert "candidates.corporate_id" in stmt


@pytest.mark.asyncio
async def test_get_client_dashboard_queries_filter_corporate(tenant_a):
    db = AsyncMock()
    db.execute.side_effect = [
        _scalar(SimpleNamespace(id=tenant_a.corporate_id, name="A", logo_url=None)),
        _scalars([]),
    ]
    out = await ClientPackageService.get_client_dashboard(db, tenant_a.corporate_id)
    assert out.packages == []
    pkg_stmt = str(db.execute.await_args_list[1].args[0])
    assert "packages.corporate_id" in pkg_stmt
