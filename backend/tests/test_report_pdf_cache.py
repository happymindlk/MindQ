"""Rendered-PDF caching: composite cache key, storage helpers, and the PDF route."""
from __future__ import annotations

import io
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from botocore.exceptions import ClientError
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.v1.reports import router
from app.auth import HRUserContext, get_current_hr_user
from app.database import get_db
from app.schemas.mindq_report import AssessmentBreakdownItem, MindQReportResponse
from app.services import report_cache, storage
from app.services.report_cache import report_cache_key

CORP = uuid.uuid4()
CANDIDATE = uuid.uuid4()
PDF = b"%PDF-1.7 rendered"


def _report(**overrides) -> MindQReportResponse:
    base = dict(
        candidate_id=CANDIDATE,
        company_name="Acme",
        candidate_full_name="Pat Lee",
        candidate_email="pat@ex.com",
        target_role="Analyst",
        total_assessments_completed=1,
        executive_summary="Strong SQL fundamentals.",
        strengths=["Solid indexing rationale."],
        competency_breakdown=[
            AssessmentBreakdownItem(
                category="Technical",
                assessment_name="SQL Basics",
                score=80.0,
                performance_summary="Strong SQL.",
            )
        ],
        synthesis_status="ok",
    )
    base.update(overrides)
    return MindQReportResponse(**base)


# --- cache key -----------------------------------------------------------------


def test_cache_key_is_stable_for_identical_reports():
    assert report_cache_key(_report()) == report_cache_key(_report())


def test_narrative_change_breaks_only_the_narrative_hash():
    before = report_cache_key(_report())
    after = report_cache_key(_report(executive_summary="Rewritten summary."))
    assert after.narrative_hash != before.narrative_hash
    assert after.scores_hash == before.scores_hash
    assert after.key != before.key


def test_score_change_breaks_only_the_scores_hash():
    before = report_cache_key(_report())
    regraded = _report(
        competency_breakdown=[
            AssessmentBreakdownItem(
                category="Technical",
                assessment_name="SQL Basics",
                score=85.0,
                performance_summary="Strong SQL.",
            )
        ]
    )
    after = report_cache_key(regraded)
    assert after.scores_hash != before.scores_hash
    assert after.narrative_hash == before.narrative_hash
    assert after.key != before.key


@pytest.mark.parametrize(
    "overrides",
    [
        {"company_logo_url": "https://cdn.example.com/new-logo.png"},
        {"candidate_full_name": "Pat Lee-Smith"},
        {"synthesis_status": "generating", "executive_summary": "", "strengths": []},
    ],
)
def test_any_rendered_field_change_breaks_the_key(overrides):
    assert report_cache_key(_report(**overrides)).key != report_cache_key(_report()).key


def test_template_or_render_version_change_breaks_the_key(monkeypatch):
    before = report_cache_key(_report()).key
    monkeypatch.setattr(report_cache, "RENDER_VERSION", "999")
    assert report_cache_key(_report()).key != before

    monkeypatch.setattr(report_cache, "RENDER_VERSION", "3")
    report_cache.template_hash.cache_clear()
    monkeypatch.setattr(report_cache, "template_hash", lambda: "0" * 64)
    assert report_cache_key(_report()).key != before


# --- storage helpers -----------------------------------------------------------


def _storage_settings(**overrides):
    base = dict(
        r2_reports_configured=True,
        R2_REPORTS_BUCKET_NAME="mindq-reports-private",
        R2_BUCKET_NAME="assess-pulse",
        SUPABASE_LOGO_BUCKET="corporate-logos",
        r2_public_base="https://cdn.example.com",
        supabase_logo_public_base="",
    )
    base.update(overrides)
    return SimpleNamespace(**base)


@pytest.fixture
def s3(monkeypatch):
    monkeypatch.setattr(storage, "settings", _storage_settings())
    client = MagicMock()
    monkeypatch.setattr(storage, "_s3_client", lambda: client)
    return client


KEY = "a" * 64


def test_fetch_cached_report_hit_reads_versioned_private_object(s3):
    s3.get_object.return_value = {"Body": io.BytesIO(PDF)}
    assert storage.fetch_cached_report(CORP, CANDIDATE, KEY) == PDF
    kwargs = s3.get_object.call_args.kwargs
    assert kwargs == {"Bucket": "mindq-reports-private", "Key": f"{CORP}/{CANDIDATE}/{KEY}.pdf"}


def test_fetch_cached_report_miss_returns_none(s3):
    s3.get_object.side_effect = ClientError({"Error": {"Code": "NoSuchKey"}}, "GetObject")
    assert storage.fetch_cached_report(CORP, CANDIDATE, KEY) is None


def test_fetch_cached_report_storage_outage_falls_back_to_render(s3):
    s3.get_object.side_effect = ClientError({"Error": {"Code": "AccessDenied"}}, "GetObject")
    assert storage.fetch_cached_report(CORP, CANDIDATE, KEY) is None
    s3.get_object.side_effect = ConnectionError("endpoint unreachable")
    assert storage.fetch_cached_report(CORP, CANDIDATE, KEY) is None


def test_cache_refuses_public_logo_bucket(monkeypatch):
    monkeypatch.setattr(
        storage, "settings", _storage_settings(R2_REPORTS_BUCKET_NAME="assess-pulse")
    )
    client = MagicMock()
    monkeypatch.setattr(storage, "_s3_client", lambda: client)
    assert storage.fetch_cached_report(CORP, CANDIDATE, KEY) is None
    assert storage.store_cached_report(CORP, CANDIDATE, KEY, PDF) is None
    client.get_object.assert_not_called()
    client.put_object.assert_not_called()


@pytest.mark.parametrize("bad", ["../../etc/passwd", "A" * 64, "a" * 63, ""])
def test_cache_key_must_be_a_sha256_digest(s3, bad):
    with pytest.raises(ValueError):
        storage.fetch_cached_report(CORP, CANDIDATE, bad)


def test_store_cached_report_prunes_older_versions_only(s3):
    new_key = f"{CORP}/{CANDIDATE}/{KEY}.pdf"
    old_key = f"{CORP}/{CANDIDATE}/{'b' * 64}.pdf"
    s3.list_objects_v2.return_value = {"Contents": [{"Key": new_key}, {"Key": old_key}]}
    assert storage.store_cached_report(CORP, CANDIDATE, KEY, PDF) == new_key
    put = s3.put_object.call_args.kwargs
    assert (put["Bucket"], put["Key"], put["ContentType"]) == (
        "mindq-reports-private",
        new_key,
        "application/pdf",
    )
    assert s3.list_objects_v2.call_args.kwargs["Prefix"] == f"{CORP}/{CANDIDATE}/"
    deleted = s3.delete_objects.call_args.kwargs["Delete"]["Objects"]
    assert deleted == [{"Key": old_key}]


def test_store_cached_report_prune_failure_keeps_upload(s3):
    s3.list_objects_v2.side_effect = ClientError({"Error": {"Code": "AccessDenied"}}, "List")
    assert storage.store_cached_report(CORP, CANDIDATE, KEY, PDF)


def test_store_cached_report_upload_failure_returns_none(s3):
    s3.put_object.side_effect = ClientError({"Error": {"Code": "SlowDown"}}, "PutObject")
    assert storage.store_cached_report(CORP, CANDIDATE, KEY, PDF) is None
    s3.list_objects_v2.assert_not_called()


# --- PDF route -----------------------------------------------------------------


def _client(report: MindQReportResponse) -> TestClient:
    app = FastAPI()
    app.include_router(router, prefix="/api/v1/admin/candidates")

    async def _hr():
        return HRUserContext(user_id=uuid.uuid4(), corporate_id=CORP, email="hr@t.com", role="hr")

    async def _db():
        yield AsyncMock()

    app.dependency_overrides[get_current_hr_user] = _hr
    app.dependency_overrides[get_db] = _db
    return TestClient(app)


def _get(report, *, cached, rendered=(PDF, True)):
    candidate = SimpleNamespace(id=CANDIDATE, corporate_id=CORP, package_id=uuid.uuid4())
    fetch = MagicMock(return_value=cached)
    store = MagicMock(return_value="key")
    render = MagicMock(return_value=rendered)
    with (
        patch(
            "app.api.v1.reports.CandidateService.get_candidate",
            new=AsyncMock(return_value=candidate),
        ),
        patch(
            "app.api.v1.reports.build_technical_report_data",
            new=AsyncMock(return_value=report),
        ),
        patch("app.services.report_pdf.ReportService.generate_report_bytes", new=render),
        patch("app.services.report_pdf.storage_service.fetch_cached_report", new=fetch),
        patch("app.jobs.tasks.storage_service.store_cached_report", new=store),
    ):
        res = _client(report).get(f"/api/v1/admin/candidates/{CANDIDATE}/report")
    return res, fetch, store, render


def test_cache_hit_serves_stored_pdf_without_rendering():
    report = _report()
    res, fetch, store, render = _get(report, cached=b"%PDF cached")
    assert res.status_code == 200
    assert res.content == b"%PDF cached"
    assert res.headers["X-Report-Cache"] == "HIT"
    assert res.headers["content-type"] == "application/pdf"
    assert "X-Report-Cache" in res.headers["Access-Control-Expose-Headers"]
    assert fetch.call_args.args == (CORP, CANDIDATE, report_cache_key(report).key)
    render.assert_not_called()
    store.assert_not_called()


def test_cache_miss_renders_once_and_stores_under_composite_key():
    report = _report()
    res, _fetch, store, render = _get(report, cached=None)
    assert res.status_code == 200
    assert res.content == PDF
    assert res.headers["X-Report-Cache"] == "MISS"
    render.assert_called_once()
    store.assert_called_once_with(CORP, CANDIDATE, report_cache_key(report).key, PDF)


def test_generating_report_bypasses_cache_and_shows_fallback_copy():
    report = _report(synthesis_status="generating", executive_summary="", strengths=[])
    res, fetch, store, render = _get(report, cached=b"%PDF should-not-be-read")
    assert res.status_code == 200
    assert res.content == PDF
    assert res.headers["X-Report-Cache"] == "BYPASS"
    assert res.headers["X-Report-Synthesis-Status"] == "generating"
    fetch.assert_not_called()
    store.assert_not_called()
    assert render.call_args.kwargs["report"]["synthesis_status"] == "generating"


def test_html_fallback_is_never_cached():
    res, _fetch, store, _render = _get(_report(), cached=None, rendered=(b"<html/>", False))
    assert res.status_code == 200
    assert res.headers["X-Report-Type"] == "HTML"
    store.assert_not_called()


def test_template_renders_generating_fallback_text():
    from app.services.report_service import ReportService

    html = ReportService.render_report_html(
        _report(synthesis_status="generating", executive_summary="").model_dump(mode="json")
    )
    assert "still being generated" in html
