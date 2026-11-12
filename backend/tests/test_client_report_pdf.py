"""Client-portal PDF download: tenant authorization and parity with the admin route."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import jwt
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.v1 import client as client_module
from app.api.v1.client import router as client_router
from app.api.v1.reports import router as admin_router
from app.auth import (
    ClientUserContext,
    HRUserContext,
    get_current_client_user,
    get_current_hr_user,
    issue_client_token,
)
from app.config import settings
from app.database import get_db
from app.schemas.mindq_report import MindQReportResponse
from app.security import RateLimiter
from app.services.report_cache import report_cache_key

PDF = b"%PDF-1.7 shared"


def _report(candidate_id, **overrides) -> MindQReportResponse:
    base = dict(
        candidate_id=candidate_id,
        company_name="Acme",
        candidate_full_name="Pat Lee",
        candidate_email="pat@ex.com",
        target_role="Analyst",
        total_assessments_completed=1,
        executive_summary="Strong SQL fundamentals.",
        synthesis_status="ok",
    )
    base.update(overrides)
    return MindQReportResponse(**base)


def _result(scalar):
    res = MagicMock()
    res.scalar_one_or_none.return_value = scalar
    return res


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


def _admin_app(corporate_id) -> TestClient:
    app = FastAPI()
    app.include_router(admin_router, prefix="/api/v1/admin/candidates")

    async def _db():
        yield AsyncMock()

    async def _hr():
        return HRUserContext(user_id=uuid4(), corporate_id=corporate_id, email="hr@t.com", role="hr")

    app.dependency_overrides[get_db] = _db
    app.dependency_overrides[get_current_hr_user] = _hr
    return TestClient(app)


@pytest.fixture(autouse=True)
def _fresh_limiter(monkeypatch):
    monkeypatch.setattr(client_module, "report_limiter", RateLimiter(20, 600))


@pytest.fixture
def storage():
    fetch = MagicMock(return_value=None)
    store = MagicMock(return_value="key")
    render = MagicMock(return_value=(PDF, True))
    with (
        patch("app.services.report_pdf.storage_service.fetch_cached_report", new=fetch),
        patch("app.jobs.tasks.storage_service.store_cached_report", new=store),
        patch("app.services.report_pdf.ReportService.generate_report_bytes", new=render),
    ):
        yield SimpleNamespace(fetch=fetch, store=store, render=render)


def test_cross_tenant_pdf_is_404_and_never_renders(storage):
    caller_corp = uuid4()
    db = AsyncMock()
    db.execute.return_value = _result(None)
    build = AsyncMock()

    with patch("app.api.v1.client.build_technical_report_data", new=build):
        res = _client_app(caller_corp, db).get(f"/api/v1/client/candidates/{uuid4()}/report")

    assert res.status_code == 404
    assert res.json() == {"detail": "Candidate not found"}
    build.assert_not_awaited()
    storage.fetch.assert_not_called()
    storage.render.assert_not_called()
    stmt = db.execute.await_args.args[0]
    assert "candidates.corporate_id" in str(stmt)
    assert caller_corp in stmt.compile().params.values()


def test_client_pdf_streams_shared_render_with_cache_headers(storage):
    corp, candidate_id = uuid4(), uuid4()
    candidate = SimpleNamespace(id=candidate_id, corporate_id=corp, package_id=uuid4())
    db = AsyncMock()
    db.execute.return_value = _result(candidate)
    report = _report(candidate_id)

    with patch(
        "app.api.v1.client.build_technical_report_data", new=AsyncMock(return_value=report)
    ):
        res = _client_app(corp, db).get(f"/api/v1/client/candidates/{candidate_id}/report")

    assert res.status_code == 200
    assert res.content == PDF
    assert res.headers["content-type"] == "application/pdf"
    assert res.headers["X-Report-Cache"] == "MISS"
    assert res.headers["X-Report-Type"] == "PDF"
    assert res.headers["X-Report-Synthesis-Status"] == "ok"
    assert res.headers["Cache-Control"] == "private, no-store"
    assert 'filename="MindQ Report - Pat Lee.pdf"' in res.headers["Content-Disposition"]
    assert "X-Report-Cache" in res.headers["Access-Control-Expose-Headers"]
    storage.store.assert_called_once_with(corp, candidate_id, report_cache_key(report).key, PDF)


def test_admin_and_client_share_one_cache_entry(storage):
    corp, candidate_id = uuid4(), uuid4()
    candidate = SimpleNamespace(id=candidate_id, corporate_id=corp, package_id=uuid4())
    report = _report(candidate_id)
    build = AsyncMock(return_value=report)
    db = AsyncMock()
    db.execute.return_value = _result(candidate)

    with (
        patch("app.api.v1.client.build_technical_report_data", new=build),
        patch("app.api.v1.reports.build_technical_report_data", new=build),
        patch(
            "app.api.v1.reports.CandidateService.get_candidate",
            new=AsyncMock(return_value=candidate),
        ),
    ):
        admin = _admin_app(corp).get(f"/api/v1/admin/candidates/{candidate_id}/report")
        client = _client_app(corp, db).get(f"/api/v1/client/candidates/{candidate_id}/report")

    assert admin.status_code == client.status_code == 200
    assert admin.content == client.content
    admin_lookup, client_lookup = storage.fetch.call_args_list
    assert admin_lookup.args == client_lookup.args == (corp, candidate_id, report_cache_key(report).key)


def test_client_pdf_serves_cache_hit_without_rendering(storage):
    corp, candidate_id = uuid4(), uuid4()
    candidate = SimpleNamespace(id=candidate_id, corporate_id=corp, package_id=uuid4())
    db = AsyncMock()
    db.execute.return_value = _result(candidate)
    storage.fetch.return_value = b"%PDF cached"

    with patch(
        "app.api.v1.client.build_technical_report_data",
        new=AsyncMock(return_value=_report(candidate_id)),
    ):
        res = _client_app(corp, db).get(f"/api/v1/client/candidates/{candidate_id}/report")

    assert res.content == b"%PDF cached"
    assert res.headers["X-Report-Cache"] == "HIT"
    storage.render.assert_not_called()


def test_client_pdf_while_generating_bypasses_cache(storage):
    corp, candidate_id = uuid4(), uuid4()
    candidate = SimpleNamespace(id=candidate_id, corporate_id=corp, package_id=uuid4())
    db = AsyncMock()
    db.execute.return_value = _result(candidate)
    report = _report(candidate_id, synthesis_status="generating", executive_summary="")

    with patch(
        "app.api.v1.client.build_technical_report_data", new=AsyncMock(return_value=report)
    ):
        res = _client_app(corp, db).get(f"/api/v1/client/candidates/{candidate_id}/report")

    assert res.status_code == 200
    assert res.headers["X-Report-Cache"] == "BYPASS"
    assert res.headers["X-Report-Synthesis-Status"] == "generating"
    storage.fetch.assert_not_called()
    storage.store.assert_not_called()


def test_client_pdf_is_rate_limited_per_user(monkeypatch, storage):
    monkeypatch.setattr(client_module, "report_limiter", RateLimiter(1, 600))
    db = AsyncMock()
    db.execute.return_value = _result(None)
    app = _client_app(uuid4(), db)
    path = f"/api/v1/client/candidates/{uuid4()}/report"
    same_user = ClientUserContext(user_id=uuid4(), corporate_id=uuid4())
    app.app.dependency_overrides[get_current_client_user] = lambda: same_user

    assert app.get(path).status_code == 404
    assert app.get(path).status_code == 429


def _supabase_hr_token() -> str:
    now = datetime.now(timezone.utc)
    return jwt.encode(
        {
            "sub": str(uuid4()),
            "aud": "authenticated",
            "email": "hr@acme.test",
            "app_metadata": {"corporate_id": str(uuid4()), "corporate_role": "hr"},
            "iat": now,
            "exp": now + timedelta(minutes=5),
        },
        settings.SUPABASE_JWT_SECRET,
        algorithm="HS256",
    )


def test_client_pdf_rejects_non_client_tokens():
    app = FastAPI()
    app.include_router(client_router, prefix="/api/v1/client")
    path = f"/api/v1/client/candidates/{uuid4()}/report"
    client = TestClient(app)

    assert client.get(path).status_code == 401
    assert client.get(path, headers={"Authorization": f"Bearer {_supabase_hr_token()}"}).status_code == 401


def test_client_token_cannot_use_admin_pdf_route():
    token, _ttl = issue_client_token(uuid4(), uuid4(), "hr@acme.test")
    app = FastAPI()
    app.include_router(admin_router, prefix="/api/v1/admin/candidates")
    res = TestClient(app).get(
        f"/api/v1/admin/candidates/{uuid4()}/report",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert res.status_code == 401
