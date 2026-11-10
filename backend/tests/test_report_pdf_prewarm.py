"""Background PDF cache warmer after package completion."""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from app.schemas.mindq_report import MindQReportResponse
from app.services import background


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
        "app.api.v1.candidate_reports.build_technical_report_data", build
    )
    store = AsyncMock()
    monkeypatch.setattr("app.services.report_pdf.render_and_store_report", store)

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
        "app.api.v1.candidate_reports.build_technical_report_data",
        AsyncMock(return_value=_report(candidate_id, synthesis_status="generating")),
    )
    store = AsyncMock()
    monkeypatch.setattr("app.services.report_pdf.render_and_store_report", store)

    await background.prewarm_report_pdf(candidate_id)

    store.assert_not_awaited()


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
        "app.api.v1.candidate_reports.build_technical_report_data",
        AsyncMock(return_value=report),
    )
    store = AsyncMock()
    monkeypatch.setattr("app.services.report_pdf.render_and_store_report", store)

    await background.prewarm_report_pdf(candidate_id)

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
