"""Client-portal bulk ZIP export: tenant auth, shared render cache, soft-fails."""
from __future__ import annotations

import io
import zipfile
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.v1 import client as client_module
from app.api.v1.client import router as client_router
from app.auth import ClientUserContext, get_current_client_user
from app.database import get_db
from app.schemas.mindq_report import MindQReportResponse
from app.security import RateLimiter
from app.services.report_cache import report_cache_key

PDF_A = b"%PDF-1.7 alice"
PDF_B = b"%PDF-1.7 bob"


def _report(candidate_id, name="Pat Lee", **overrides) -> MindQReportResponse:
    base = dict(
        candidate_id=candidate_id,
        company_name="Acme",
        candidate_full_name=name,
        candidate_email="pat@ex.com",
        target_role="Analyst",
        total_assessments_completed=1,
        executive_summary="Strong SQL fundamentals.",
        synthesis_status="ok",
    )
    base.update(overrides)
    return MindQReportResponse(**base)


def _client_app(corporate_id, db) -> TestClient:
    app = FastAPI()
    app.include_router(client_router, prefix="/api/v1/client")

    async def _db():
        yield db

    async def _client_user():
        return ClientUserContext(user_id=uuid4(), corporate_id=corporate_id)

    app.dependency_overrides[get_db] = _db
    app.dependency_overrides[get_current_client_user] = _client_user
    return TestClient(app)


@pytest.fixture(autouse=True)
def _fresh_limiter(monkeypatch):
    monkeypatch.setattr(client_module, "reports_zip_limiter", RateLimiter(5, 600))


@pytest.fixture(autouse=True)
def _fake_session_local(monkeypatch):
    """ZIP workers open per-candidate sessions; keep tests off the real pool."""
    session = AsyncMock()
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=None)
    monkeypatch.setattr(client_module, "SessionLocal", MagicMock(return_value=session))


@pytest.fixture
def storage():
    fetch = MagicMock(return_value=None)
    store = MagicMock(return_value="key")
    render = MagicMock(side_effect=[(PDF_A, True), (PDF_B, True)])
    with (
        patch("app.services.report_pdf.storage_service.fetch_cached_report", new=fetch),
        patch("app.services.report_pdf.storage_service.store_cached_report", new=store),
        patch("app.services.report_pdf.ReportService.generate_report_bytes", new=render),
    ):
        yield SimpleNamespace(fetch=fetch, store=store, render=render)


def test_cross_tenant_package_zip_is_404(storage):
    db = AsyncMock()
    lookup = AsyncMock(side_effect=LookupError("Package not found"))

    with patch(
        "app.api.v1.client.ClientPackageService.get_package_completed_candidates",
        new=lookup,
    ):
        res = _client_app(uuid4(), db).get(f"/api/v1/client/packages/{uuid4()}/reports-zip")

    assert res.status_code == 404
    assert res.json() == {"detail": "Package not found"}
    storage.render.assert_not_called()


def test_empty_completed_roster_is_404(storage):
    corp, package_id = uuid4(), uuid4()
    package = SimpleNamespace(id=package_id, title="Senior Engineer", corporate_id=corp)
    db = AsyncMock()

    with patch(
        "app.api.v1.client.ClientPackageService.get_package_completed_candidates",
        new=AsyncMock(return_value=(package, [])),
    ):
        res = _client_app(corp, db).get(f"/api/v1/client/packages/{package_id}/reports-zip")

    assert res.status_code == 404
    assert res.json() == {"detail": "No completed reports to download"}
    storage.render.assert_not_called()


def test_reports_zip_streams_store_compressed_archive(storage):
    corp, package_id = uuid4(), uuid4()
    alice_id, bob_id = uuid4(), uuid4()
    package = SimpleNamespace(id=package_id, title="Senior Engineer", corporate_id=corp)
    alice = SimpleNamespace(
        id=alice_id, corporate_id=corp, package_id=package_id, full_name="Alice A"
    )
    bob = SimpleNamespace(
        id=bob_id, corporate_id=corp, package_id=package_id, full_name="Bob B"
    )
    db = AsyncMock()
    build = AsyncMock(
        side_effect=[
            _report(alice_id, name="Alice A"),
            _report(bob_id, name="Bob B"),
        ]
    )

    with (
        patch(
            "app.api.v1.client.ClientPackageService.get_package_completed_candidates",
            new=AsyncMock(return_value=(package, [alice, bob])),
        ),
        patch("app.api.v1.client.build_technical_report_data", new=build),
    ):
        res = _client_app(corp, db).get(f"/api/v1/client/packages/{package_id}/reports-zip")

    assert res.status_code == 200
    assert res.headers["content-type"] == "application/zip"
    assert res.headers["X-Report-Zip-Count"] == "2"
    assert res.headers["X-Report-Zip-Failed"] == "0"
    assert res.headers["Cache-Control"] == "private, no-store"
    assert 'filename="MindQ Reports - Senior Engineer.zip"' in res.headers["Content-Disposition"]

    with zipfile.ZipFile(io.BytesIO(res.content)) as archive:
        names = sorted(archive.namelist())
        assert names == [
            "MindQ Report - Alice A.pdf",
            "MindQ Report - Bob B.pdf",
        ]
        # Concurrent renders: PDF bytes are unordered relative to name sort.
        assert {archive.read(names[0]), archive.read(names[1])} == {PDF_A, PDF_B}
        assert archive.getinfo(names[0]).compress_type == zipfile.ZIP_STORED

    assert storage.render.call_count == 2
    assert storage.store.call_count == 2
    stored_ids = {call.args[1] for call in storage.store.call_args_list}
    assert stored_ids == {alice_id, bob_id}
    stored_keys = {call.args[2] for call in storage.store.call_args_list}
    assert stored_keys == {
        report_cache_key(_report(alice_id, name="Alice A")).key,
        report_cache_key(_report(bob_id, name="Bob B")).key,
    }


def test_reports_zip_soft_skips_failed_candidates(storage):
    corp, package_id = uuid4(), uuid4()
    ok_id, bad_id = uuid4(), uuid4()
    package = SimpleNamespace(id=package_id, title="Round", corporate_id=corp)
    ok = SimpleNamespace(id=ok_id, corporate_id=corp, package_id=package_id, full_name="Ok")
    bad = SimpleNamespace(id=bad_id, corporate_id=corp, package_id=package_id, full_name="Bad")
    db = AsyncMock()
    build = AsyncMock(
        side_effect=[
            RuntimeError("synthesis blew up"),
            _report(ok_id, name="Ok"),
        ]
    )
    storage.render.side_effect = [(PDF_A, True)]

    with (
        patch(
            "app.api.v1.client.ClientPackageService.get_package_completed_candidates",
            new=AsyncMock(return_value=(package, [bad, ok])),
        ),
        patch("app.api.v1.client.build_technical_report_data", new=build),
    ):
        res = _client_app(corp, db).get(f"/api/v1/client/packages/{package_id}/reports-zip")

    assert res.status_code == 200
    assert res.headers["X-Report-Zip-Count"] == "1"
    assert res.headers["X-Report-Zip-Failed"] == "1"
    with zipfile.ZipFile(io.BytesIO(res.content)) as archive:
        assert archive.namelist() == ["MindQ Report - Ok.pdf"]


def test_reports_zip_all_failures_are_502(storage):
    corp, package_id = uuid4(), uuid4()
    package = SimpleNamespace(id=package_id, title="Round", corporate_id=corp)
    cand = SimpleNamespace(
        id=uuid4(), corporate_id=corp, package_id=package_id, full_name="X"
    )
    db = AsyncMock()

    with (
        patch(
            "app.api.v1.client.ClientPackageService.get_package_completed_candidates",
            new=AsyncMock(return_value=(package, [cand])),
        ),
        patch(
            "app.api.v1.client.build_technical_report_data",
            new=AsyncMock(side_effect=RuntimeError("boom")),
        ),
    ):
        res = _client_app(corp, db).get(f"/api/v1/client/packages/{package_id}/reports-zip")

    assert res.status_code == 502
    assert res.json() == {"detail": "No reports could be generated"}
    storage.render.assert_not_called()


def test_reports_zip_is_rate_limited_separately_from_single_pdf(monkeypatch, storage):
    monkeypatch.setattr(client_module, "reports_zip_limiter", RateLimiter(1, 600))
    corp, package_id = uuid4(), uuid4()
    package = SimpleNamespace(id=package_id, title="Round", corporate_id=corp)
    db = AsyncMock()
    lookup = AsyncMock(return_value=(package, []))
    app = _client_app(corp, db)
    same_user = ClientUserContext(user_id=uuid4(), corporate_id=corp)
    app.app.dependency_overrides[get_current_client_user] = lambda: same_user
    path = f"/api/v1/client/packages/{package_id}/reports-zip"

    with patch(
        "app.api.v1.client.ClientPackageService.get_package_completed_candidates",
        new=lookup,
    ):
        assert app.get(path).status_code == 404
        assert app.get(path).status_code == 429


def test_unique_names_for_duplicate_candidates(storage):
    from app.services.report_zip import unique_zip_filename

    used: set[str] = set()
    assert unique_zip_filename("MindQ Report - Jane.pdf", used) == "MindQ Report - Jane.pdf"
    assert unique_zip_filename("MindQ Report - Jane.pdf", used) == "MindQ Report - Jane (2).pdf"
    assert unique_zip_filename("MindQ Report - jane.pdf", used) == "MindQ Report - jane (3).pdf"
