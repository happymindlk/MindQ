"""Background PDF cache warmer after package completion."""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from app.api.v1 import candidate_reports
from app.schemas.mindq_report import MindQReportResponse
from app.services import background
from app.services.report_pdf import RenderedReport, render_report


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


@pytest.mark.asyncio
async def test_prewarm_skips_incomplete_package(monkeypatch):
    candidate_id = uuid4()
    candidate = SimpleNamespace(id=candidate_id, corporate_id=uuid4())
    session = MagicMock()
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=None)
    monkeypatch.setattr(background, "SessionLocal", MagicMock(return_value=session))
    monkeypatch.setattr(
        background.CandidateService, "get_candidate", AsyncMock(return_value=candidate)
    )
    monkeypatch.setattr(
        background.CandidateService,
        "is_package_complete",
        AsyncMock(return_value=False),
    )
    build = AsyncMock()
    monkeypatch.setattr(
        "app.api.v1.candidate_reports.assemble_technical_report_data", build
    )
    store = AsyncMock()
    monkeypatch.setattr("app.services.report_pdf.render_and_store_report", store)
    monkeypatch.setattr(
        "app.services.report_snapshot.upsert_report_snapshot", AsyncMock()
    )

    await background.prewarm_report_pdf(candidate_id)

    build.assert_not_awaited()
    store.assert_not_awaited()


@pytest.mark.asyncio
async def test_prewarm_skips_generating_synthesis(monkeypatch):
    candidate_id = uuid4()
    corporate_id = uuid4()
    candidate = SimpleNamespace(id=candidate_id, corporate_id=corporate_id)
    session = MagicMock()
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=None)
    monkeypatch.setattr(background, "SessionLocal", MagicMock(return_value=session))
    monkeypatch.setattr(
        background.CandidateService, "get_candidate", AsyncMock(return_value=candidate)
    )
    monkeypatch.setattr(
        background.CandidateService,
        "is_package_complete",
        AsyncMock(return_value=True),
    )
    monkeypatch.setattr(
        "app.api.v1.candidate_reports.assemble_technical_report_data",
        AsyncMock(return_value=_report(candidate_id, synthesis_status="generating")),
    )
    store = AsyncMock()
    monkeypatch.setattr("app.services.report_pdf.render_and_store_report", store)
    snapshot = AsyncMock()
    monkeypatch.setattr("app.services.report_snapshot.upsert_report_snapshot", snapshot)

    await background.prewarm_report_pdf(candidate_id)

    store.assert_not_awaited()
    snapshot.assert_not_awaited()


@pytest.mark.asyncio
async def test_prewarm_renders_and_stores_when_ready(monkeypatch):
    candidate_id = uuid4()
    corporate_id = uuid4()
    candidate = SimpleNamespace(id=candidate_id, corporate_id=corporate_id)
    report = _report(candidate_id)
    session = MagicMock()
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=None)
    monkeypatch.setattr(background, "SessionLocal", MagicMock(return_value=session))
    monkeypatch.setattr(
        background.CandidateService, "get_candidate", AsyncMock(return_value=candidate)
    )
    monkeypatch.setattr(
        background.CandidateService,
        "is_package_complete",
        AsyncMock(return_value=True),
    )
    monkeypatch.setattr(
        "app.api.v1.candidate_reports.assemble_technical_report_data",
        AsyncMock(return_value=report),
    )
    snapshot = AsyncMock()
    monkeypatch.setattr("app.services.report_snapshot.upsert_report_snapshot", snapshot)
    store = AsyncMock()
    monkeypatch.setattr("app.services.report_pdf.render_and_store_report", store)

    await background.prewarm_report_pdf(candidate_id)

    snapshot.assert_awaited_once()
    store.assert_awaited_once()
    assert store.await_args.kwargs["corporate_id"] == corporate_id
    assert store.await_args.kwargs["candidate_id"] == candidate_id
    assert store.await_args.args[0] is report


@pytest.mark.asyncio
async def test_finalize_queues_pdf_prewarm(monkeypatch):
    candidate_id = uuid4()
    assessment_id = uuid4()
    candidate = SimpleNamespace(id=candidate_id)
    session = MagicMock()
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=None)
    monkeypatch.setattr(background, "SessionLocal", MagicMock(return_value=session))
    monkeypatch.setattr(
        background.CandidateService, "get_candidate", AsyncMock(return_value=candidate)
    )
    monkeypatch.setattr(
        background.CandidateService,
        "finalize_submission_scores",
        AsyncMock(),
    )
    score = AsyncMock()
    notify = AsyncMock()
    prewarm = AsyncMock()
    monkeypatch.setattr(background, "score_ai_for_candidate", score)
    monkeypatch.setattr(background, "notify_hr_if_package_complete", notify)
    monkeypatch.setattr(background, "prewarm_report_pdf", prewarm)

    await background.finalize_and_score_ai(candidate_id, assessment_id)

    score.assert_awaited_once_with(candidate_id, assessment_id)
    notify.assert_awaited_once_with(candidate_id)
    prewarm.assert_awaited_once_with(candidate_id)


@pytest.mark.asyncio
async def test_finalize_runs_score_then_prewarm_in_order(monkeypatch):
    """Final-module worker must score/synthesize before snapshot+PDF prewarm."""
    candidate_id = uuid4()
    assessment_id = uuid4()
    candidate = SimpleNamespace(id=candidate_id)
    session = MagicMock()
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=None)
    monkeypatch.setattr(background, "SessionLocal", MagicMock(return_value=session))
    monkeypatch.setattr(
        background.CandidateService, "get_candidate", AsyncMock(return_value=candidate)
    )
    monkeypatch.setattr(
        background.CandidateService,
        "finalize_submission_scores",
        AsyncMock(),
    )
    order: list[str] = []

    async def _score(*_a, **_k):
        order.append("score")

    async def _notify(*_a, **_k):
        order.append("notify")

    async def _prewarm(*_a, **_k):
        order.append("prewarm")

    monkeypatch.setattr(background, "score_ai_for_candidate", _score)
    monkeypatch.setattr(background, "notify_hr_if_package_complete", _notify)
    monkeypatch.setattr(background, "prewarm_report_pdf", _prewarm)

    await background.finalize_and_score_ai(candidate_id, assessment_id)

    assert order == ["score", "notify", "prewarm"]


@pytest.mark.asyncio
async def test_prewarm_warms_held_for_review_snapshot_and_pdf(monkeypatch):
    candidate_id = uuid4()
    corporate_id = uuid4()
    candidate = SimpleNamespace(id=candidate_id, corporate_id=corporate_id)
    report = _report(candidate_id, synthesis_status="held_for_review")
    session = MagicMock()
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=None)
    monkeypatch.setattr(background, "SessionLocal", MagicMock(return_value=session))
    monkeypatch.setattr(
        background.CandidateService, "get_candidate", AsyncMock(return_value=candidate)
    )
    monkeypatch.setattr(
        background.CandidateService,
        "is_package_complete",
        AsyncMock(return_value=True),
    )
    monkeypatch.setattr(
        "app.api.v1.candidate_reports.assemble_technical_report_data",
        AsyncMock(return_value=report),
    )
    snapshot = AsyncMock()
    monkeypatch.setattr("app.services.report_snapshot.upsert_report_snapshot", snapshot)
    store = AsyncMock()
    monkeypatch.setattr("app.services.report_pdf.render_and_store_report", store)

    await background.prewarm_report_pdf(candidate_id)

    snapshot.assert_awaited_once()
    store.assert_awaited_once()


@pytest.mark.asyncio
async def test_warm_snapshot_view_skips_live_assembly(monkeypatch):
    """View Report must serve candidate_reports without Gemini/DB assembly."""
    candidate_id = uuid4()
    candidate = SimpleNamespace(
        id=candidate_id, corporate_id=uuid4(), package_id=uuid4()
    )
    warmed = _report(candidate_id)
    assemble = AsyncMock()
    monkeypatch.setattr(
        candidate_reports, "read_report_snapshot", AsyncMock(return_value=warmed)
    )
    monkeypatch.setattr(candidate_reports, "assemble_technical_report_data", assemble)

    loaded = await candidate_reports.build_technical_report_data(
        AsyncMock(), candidate
    )

    assert loaded is warmed
    assemble.assert_not_awaited()


@pytest.mark.asyncio
async def test_warm_pdf_download_skips_weasyprint_and_enqueue():
    """Download Report must hit storage without rendering or store-job enqueue."""
    candidate_id = uuid4()
    corporate_id = uuid4()
    report = _report(candidate_id)
    cached = b"%PDF-1.7 warmed"
    generate = MagicMock(side_effect=AssertionError("WeasyPrint must not run"))
    enqueue = AsyncMock(side_effect=AssertionError("store job must not enqueue"))

    with (
        patch(
            "app.services.report_pdf.storage_service.fetch_cached_report",
            return_value=cached,
        ),
        patch(
            "app.services.report_pdf.ReportService.generate_report_bytes",
            new=generate,
        ),
        patch(
            "app.services.report_pdf.enqueue_store_cached_report",
            new=enqueue,
        ),
    ):
        rendered = await render_report(
            report,
            corporate_id=corporate_id,
            candidate_id=candidate_id,
            portal="client",
        )

    assert rendered == RenderedReport(
        content=cached, is_pdf=True, cache_state="HIT"
    )
    generate.assert_not_called()
    enqueue.assert_not_awaited()


@pytest.mark.asyncio
async def test_package_complete_lifecycle_warms_then_serves_from_cache(monkeypatch):
    """Final assessment → worker prewarm → View/Download are pure cache hits."""
    candidate_id = uuid4()
    assessment_id = uuid4()
    corporate_id = uuid4()
    candidate = SimpleNamespace(
        id=candidate_id, corporate_id=corporate_id, package_id=uuid4()
    )
    report = _report(candidate_id)
    session = MagicMock()
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=None)
    monkeypatch.setattr(background, "SessionLocal", MagicMock(return_value=session))
    monkeypatch.setattr(
        background.CandidateService, "get_candidate", AsyncMock(return_value=candidate)
    )
    monkeypatch.setattr(
        background.CandidateService,
        "finalize_submission_scores",
        AsyncMock(),
    )
    monkeypatch.setattr(
        background.CandidateService,
        "is_package_complete",
        AsyncMock(return_value=True),
    )
    monkeypatch.setattr(background, "score_ai_for_candidate", AsyncMock())
    monkeypatch.setattr(background, "notify_hr_if_package_complete", AsyncMock())
    monkeypatch.setattr(
        "app.api.v1.candidate_reports.assemble_technical_report_data",
        AsyncMock(return_value=report),
    )
    snapshot = AsyncMock()
    monkeypatch.setattr("app.services.report_snapshot.upsert_report_snapshot", snapshot)
    store = AsyncMock(
        return_value=RenderedReport(
            content=b"%PDF warmed", is_pdf=True, cache_state="MISS"
        )
    )
    monkeypatch.setattr("app.services.report_pdf.render_and_store_report", store)

    await background.finalize_and_score_ai(candidate_id, assessment_id)

    snapshot.assert_awaited_once()
    store.assert_awaited_once()
    assert store.await_args.kwargs["corporate_id"] == corporate_id
    assert store.await_args.kwargs["candidate_id"] == candidate_id

    assemble = AsyncMock(side_effect=AssertionError("live assembly must not run"))
    monkeypatch.setattr(
        candidate_reports, "read_report_snapshot", AsyncMock(return_value=report)
    )
    monkeypatch.setattr(candidate_reports, "assemble_technical_report_data", assemble)
    viewed = await candidate_reports.build_technical_report_data(
        AsyncMock(), candidate
    )
    assert viewed is report
    assemble.assert_not_awaited()

    with (
        patch(
            "app.services.report_pdf.storage_service.fetch_cached_report",
            return_value=b"%PDF warmed",
        ),
        patch(
            "app.services.report_pdf.ReportService.generate_report_bytes",
            new=MagicMock(side_effect=AssertionError("WeasyPrint must not run")),
        ),
        patch(
            "app.services.report_pdf.enqueue_store_cached_report",
            new=AsyncMock(side_effect=AssertionError("store job must not enqueue")),
        ),
    ):
        downloaded = await render_report(
            report,
            corporate_id=corporate_id,
            candidate_id=candidate_id,
            portal="client",
        )
    assert downloaded.cache_state == "HIT"
    assert downloaded.content == b"%PDF warmed"
